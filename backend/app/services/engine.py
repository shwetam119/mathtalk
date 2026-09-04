"""MathTalk conversation engine.

This is the single place where a student turn becomes:
  transcript -> intent -> state transition -> pipeline -> response

Voice turns (speech transcripts) and visual turns (button/keyboard actions)
both arrive here through the same code path and mutate the same
``SessionState``.

Upgrade: an input-understanding layer sits between the deterministic command
parser and the pipeline. Short direct answers (\"4\", \"four\", \"x equals 4\")
are extracted and verified deterministically; guided step walks give the
smallest useful intervention after a wrong answer; and the LLM (Gemma) is
only consulted for ambiguous understanding and natural wording — it never
decides mathematics or state.
"""
from __future__ import annotations

import re
import time
from typing import List, Optional

from app.core.config import Settings, settings
from app.core.logging import get_logger
from app.mathematics.problems import (
    find_problem,
    list_subtopics,
    list_topics,
    related_problem,
)
from app.mathematics.spoken import extract_direct_answer, match_operation, normalize_spoken_math
from app.mathematics.verifier import verify, verify_step_expression
from app.models.schemas import (
    AppState,
    AssistanceLevel,
    Difficulty,
    InputType,
    IntentKind,
    Intervention,
    LearningMode,
    MemoryType,
    PipelineEvent,
    Problem,
    SessionState,
    StepWalk,
    TurnRecord,
    Verdict,
    VoiceStatus,
)
from app.reasoning.classifier import InputClassifier
from app.reasoning.interpreter import ReasoningInterpreter
from app.reasoning.misconception import MisconceptionDetector
from app.services.memory import QdrantMemoryService
from app.state.commands import ParsedIntent, parse_intent
from app.state.sessions import SessionManager
from app.state.state_machine import (
    bump,
    compute_available_actions,
    go_back,
    push_history,
)
from app.tutoring.policy import TutoringPolicy
from app.tutoring.responses import ResponseGenerator, number_options

log = get_logger("mathtalk.engine")

_MODES = ["Learn", "Practice", "Test", "Review"]
_DIFFICULTIES = ["Easy", "Medium", "Hard"]


class EngineResult:
    def __init__(
        self,
        session: SessionState,
        spoken: str = "",
        events: Optional[List[PipelineEvent]] = None,
        ok: bool = True,
        error: str = "",
        latency_ms: int = 0,
    ):
        self.session = session
        self.spoken = spoken
        self.events = events or []
        self.ok = ok
        self.error = error
        self.latency_ms = latency_ms

    def to_dict(self) -> dict:
        return {
            "state": self.session.model_dump(mode="json"),
            "spoken": self.spoken,
            "pipeline_events": [e.model_dump(mode="json") for e in self.events],
            "ok": self.ok,
            "error": self.error,
            "latency_ms": self.latency_ms,
        }


class MathTalkEngine:
    def __init__(
        self,
        sessions: SessionManager,
        memory: QdrantMemoryService,
        interpreter: Optional[ReasoningInterpreter] = None,
        detector: Optional[MisconceptionDetector] = None,
        policy: Optional[TutoringPolicy] = None,
        responses: Optional[ResponseGenerator] = None,
        classifier: Optional[InputClassifier] = None,
        llm=None,
        conf: Optional[Settings] = None,
    ):
        self.conf = conf or settings
        self.sessions = sessions
        self.memory = memory
        self.interpreter = interpreter or ReasoningInterpreter()
        self.detector = detector or MisconceptionDetector()
        self.policy = policy or TutoringPolicy(max_attempts_before_solution=self.conf.max_attempts_before_solution)
        self.responses = responses or ResponseGenerator()
        self.classifier = classifier or InputClassifier()
        self.llm = llm

    # ==================================================================
    # lifecycle
    # ==================================================================
    def start_session(self, session: SessionState) -> EngineResult:
        session.app_state = AppState.HOME
        session.state_history.clear()
        self._refresh_actions(session)
        spoken = self.responses.welcome(session)
        session.last_spoken = spoken
        session.voice_status = VoiceStatus.SPEAKING
        bump(session)
        return EngineResult(session, spoken=spoken)

    def set_voice_status(self, session: SessionState, status: str) -> SessionState:
        try:
            session.voice_status = VoiceStatus(status)
        except ValueError:
            pass
        bump(session)
        return session

    # ==================================================================
    # turn handling (voice and visual share this path)
    # ==================================================================
    def handle_turn(
        self,
        session: SessionState,
        transcript: str,
        source: str = "speech",
        confidence: float = 1.0,
    ) -> EngineResult:
        t0 = time.perf_counter()
        session.voice_channel = source
        text = (transcript or "").strip()
        if not text:
            return self._finish(
                session,
                spoken="I didn't hear anything. Please say that again.",
                error="empty transcript",
                t0=t0,
            )
        session.turns.append(TurnRecord(speaker="student", text=text))

        parsed = parse_intent(text, session)
        session.voice_status = VoiceStatus.PROCESSING
        # Open-ended speech goes through the input-understanding layer:
        # one-word answers, stuck signals, questions and reasoning all land here.
        if parsed.kind == IntentKind.SUBMIT_REASONING:
            return self._handle_open_speech(session, parsed.matched_text or text, t0)
        result = self.handle_intent(session, parsed, t0)
        return result

    # ------------------------------------------------------------------
    def handle_intent(self, session: SessionState, parsed: ParsedIntent, t0: Optional[float] = None) -> EngineResult:
        t0 = t0 or time.perf_counter()
        kind = parsed.kind
        option = parsed.option

        # Record the state we are leaving so GO_BACK can retrace (deduped).
        push_history(session)

        # -------- global commands -------------------------------------
        if kind == IntentKind.HELP:
            return self._finish(session, spoken=self.responses.help_text(session), t0=t0)
        if kind == IntentKind.REPEAT:
            spoken = session.last_spoken or self._prompt_for(session)
            return self._finish(session, spoken=spoken, t0=t0)
        if kind == IntentKind.GO_BACK:
            target = go_back(session)
            session.app_state = target
            session.pending_confirmation = None
            self._clear_problem_context(session)
            self._refresh_actions(session)
            spoken = self._prompt_for(session)
            return self._finish(session, spoken=spoken, t0=t0)
        if kind == IntentKind.GO_HOME:
            session.app_state = AppState.HOME
            session.state_history.clear()
            self._clear_problem_context(session)
            session.mode = None
            session.topic = None
            session.subtopic = None
            session.difficulty = None
            session.pending_confirmation = None
            self._refresh_actions(session)
            spoken = self.responses.welcome(session)
            session.last_spoken = spoken
            return self._finish(session, spoken=spoken, t0=t0)
        if kind == IntentKind.STOP:
            session.paused = True
            session.voice_status = VoiceStatus.IDLE
            bump(session)
            return EngineResult(session, spoken="Paused. Say resume to continue.")
        if kind == IntentKind.RESUME:
            session.paused = False
            spoken = session.last_spoken or self._prompt_for(session)
            return self._finish(session, spoken=spoken, t0=t0)
        if kind == IntentKind.END_SESSION:
            return self._end_session(session, t0)

        # -------- state-specific handling ------------------------------
        if session.paused and kind not in (IntentKind.RESUME, IntentKind.HELP):
            return self._finish(
                session, spoken="I'm paused. Say resume to continue.", t0=t0
            )

        if kind == IntentKind.CONFIRM_YES:
            return self._confirm(session, yes=True, t0=t0)
        if kind == IntentKind.CONFIRM_NO:
            return self._confirm(session, yes=False, t0=t0)

        if kind == IntentKind.SUBMIT_REASONING:
            # if the student speaks reasoning right after an intervention,
            # treat it as "try again" + reasoning in one turn
            if session.app_state == AppState.INTERVENTION:
                session.app_state = AppState.REASONING
                self._refresh_actions(session)
            return self._run_reasoning_pipeline(session, parsed.matched_text, t0)

        if kind == IntentKind.REQUEST_HINT:
            return self._give_hint(session, t0)
        if kind == IntentKind.REVIEW_APPROACH:
            return self._review_approach(session, t0)
        if kind == IntentKind.TRY_AGAIN:
            return self._try_again(session, t0)
        if kind == IntentKind.SHOW_SOLUTION:
            return self._show_solution(session, t0)
        if kind == IntentKind.NEXT_PROBLEM:
            return self._next_problem(session, t0)
        if kind == IntentKind.PRACTICE_MORE:
            return self._practice_more(session, t0)
        if kind == IntentKind.START_NEW_SESSION:
            return self._start_new_session(session, t0)

        if kind == IntentKind.SELECT_OPTION:
            return self._select_option(session, option, t0)

        # -------- unknown ----------------------------------------------
        return self._finish(
            session,
            spoken=self.responses.reprocess(session),
            error="unrecognized input",
            t0=t0,
        )

    # ==================================================================
    # input understanding (open-ended speech)
    # ==================================================================
    def _handle_open_speech(self, session: SessionState, text: str, t0: float) -> EngineResult:
        problem = session.current_problem
        # speaking right after an intervention = trying again
        if session.app_state == AppState.INTERVENTION:
            session.app_state = AppState.REASONING
            self._refresh_actions(session)

        classification = self.classifier.classify_with_llm(text, session, problem)
        session.input_type = classification.input_type.value
        session.extracted_answer = None
        pre = [PipelineEvent(
            stage="classifier",
            label=f"Input understood: {classification.input_type.value}",
            detail=f"{classification.source} · confidence {classification.confidence:.2f}",
            ok=True,
        )]

        # inside a guided step walk, only answer-like turns are step responses;
        # stuck / question / yes-no turns get their normal supportive handling
        if session.step_walk:
            if classification.input_type == InputType.REQUEST_FOR_HELP:
                return self._handle_stuck(session, text, pre, t0)
            if classification.input_type == InputType.QUESTION:
                return self._handle_question(session, text, pre, t0)
            if classification.input_type in (InputType.UNCERTAIN, InputType.OTHER,
                                             InputType.REASONING, InputType.DIRECT_ANSWER):
                return self._handle_step_response(session, text, t0)
            return self._handle_yes_no(session, yes=classification.input_type == InputType.CONFIRMATION, t0=t0)

        if classification.input_type == InputType.DIRECT_ANSWER and classification.direct_answer:
            return self._handle_direct_answer(session, classification.direct_answer, pre, t0)
        if classification.input_type in (InputType.CONFIRMATION, InputType.REJECTION):
            return self._handle_yes_no(session, yes=classification.input_type == InputType.CONFIRMATION, t0=t0)
        if classification.input_type == InputType.REQUEST_FOR_HELP:
            return self._handle_stuck(session, text, pre, t0)
        if classification.input_type == InputType.QUESTION:
            return self._handle_question(session, text, pre, t0)
        if classification.input_type == InputType.REASONING:
            return self._run_reasoning_pipeline(session, text, t0, pre_events=pre)
        # UNCERTAIN / OTHER -> short clarification
        return self._handle_uncertain(session, text, pre, t0)

    # ------------------------------------------------------------------
    def _handle_direct_answer(self, session: SessionState, answer, pre: List[PipelineEvent], t0: float) -> EngineResult:
        problem = session.current_problem
        if problem is None:
            return self._finish(session, spoken=self.responses.reprocess(session), error="no active problem", t0=t0)
        session.extracted_answer = answer.answer_expression
        structured = self.interpreter.from_direct_answer(problem, answer)
        return self._complete_pipeline(
            session, problem, structured, answer.raw_text, [], t0,
            from_direct=True, pre_events=pre,
        )

    # ------------------------------------------------------------------
    def _handle_stuck(self, session: SessionState, text: str, pre: List[PipelineEvent], t0: float) -> EngineResult:
        problem = session.current_problem
        if problem and problem.tutoring_steps and session.step_walk:
            idx = session.step_walk.step_index
            if 0 <= idx < len(problem.tutoring_steps):
                step = problem.tutoring_steps[idx]
                spoken = self.responses.step_stuck(step)
                session.app_state = AppState.REASONING
                session.last_spoken = spoken
                self._refresh_actions(session)
                return self._finish(session, spoken=spoken, t0=t0, events=pre + [PipelineEvent(
                    stage="response", label="Supportive step hint", detail=spoken[:90], ok=False)])
        if problem:
            level = max(session.assistance_level, AssistanceLevel.HINT)
            session.assistance_level = level
            session.session_progress.hints_used += 1
            spoken = self.responses.stuck_response(problem)
            session.app_state = AppState.REASONING
            session.last_spoken = spoken
            self._refresh_actions(session)
            return self._finish(session, spoken=spoken, t0=t0, events=pre + [PipelineEvent(
                stage="response", label="Supportive response", detail=spoken[:90], ok=False)])
        return self._finish(
            session,
            spoken="No problem. Take your time — say repeat if you want me to say the options again.",
            t0=t0, events=pre,
        )

    def _handle_question(self, session: SessionState, text: str, pre: List[PipelineEvent], t0: float) -> EngineResult:
        problem = session.current_problem
        spoken = self.responses.question_response(problem) if problem else self.responses.welcome(session)
        session.last_spoken = spoken
        self._refresh_actions(session)
        return self._finish(session, spoken=spoken, t0=t0, events=pre + [PipelineEvent(
            stage="response", label="Question acknowledged", detail=spoken[:90])])

    def _handle_yes_no(self, session: SessionState, yes: bool, t0: float) -> EngineResult:
        # bare yes/no with nothing pending: acknowledge and re-prompt naturally
        lead = "Great — go ahead." if yes else "No problem."
        spoken = f"{lead} {self._prompt_for(session)}"
        session.last_spoken = spoken
        return self._finish(session, spoken=spoken, t0=t0)

    def _handle_uncertain(self, session: SessionState, text: str, pre: List[PipelineEvent], t0: float) -> EngineResult:
        norm = normalize_spoken_math(text)
        nums = re.findall(r"-?\d+(?:\.\d+)?(?:/\d+)?", norm)  # noqa: W605
        if nums:
            spoken = self.responses.ambiguous_number(nums[-1])
        else:
            spoken = self.responses.reprocess(session)
        session.last_spoken = spoken
        self._refresh_actions(session)
        return self._finish(session, spoken=spoken, t0=t0, events=pre + [PipelineEvent(
            stage="response", label="Clarification asked", detail=spoken[:90], ok=False)])

    # ==================================================================
    # guided step walk
    # ==================================================================
    def _enter_step_walk(
        self, session, problem, structured, verification, misconception, intervention, events, t0,
    ) -> EngineResult:
        session.step_walk = StepWalk(
            problem_id=problem.problem_id, step_index=0, step_attempts=0,
            total_steps=len(problem.tutoring_steps), started_from="wrong_answer",
        )
        step = problem.tutoring_steps[0]
        spoken = self._polish(session, problem, self.responses.step_question(step, first=True), {"step": step.question})
        session.app_state = AppState.REASONING
        session.structured_reasoning = structured
        session.verification_result = verification
        session.misconception = misconception
        session.selected_intervention = intervention
        session.assistance_level = AssistanceLevel.REVIEW_APPROACH
        session.last_spoken = spoken
        session.last_pipeline_events = events + [PipelineEvent(
            stage="response", label="Step-focused tutoring started", detail=spoken[:90], ok=False)]
        self._refresh_actions(session)
        session.voice_status = VoiceStatus.SPEAKING
        return EngineResult(session, spoken=spoken, events=session.last_pipeline_events,
                            latency_ms=int((time.perf_counter() - t0) * 1000))

    def _handle_step_response(self, session: SessionState, text: str, t0: float) -> EngineResult:
        problem = session.current_problem
        if problem is None or not problem.tutoring_steps or not session.step_walk:
            session.step_walk = None
            return self._run_reasoning_pipeline(session, text, t0)
        idx = session.step_walk.step_index
        if idx >= len(problem.tutoring_steps):
            session.step_walk = None
            return self._run_reasoning_pipeline(session, text, t0)
        step = problem.tutoring_steps[idx]
        session.input_type = InputType.DIRECT_ANSWER.value

        if step.expected_op:
            op = match_operation(text, [step.expected_op] + step.op_accept)
            ok = op is not None
        else:
            norm = normalize_spoken_math(text)
            ok = verify_step_expression(norm, step.expected_expr or "")
            if not ok:
                da = extract_direct_answer(text)
                if da:
                    session.extracted_answer = da.answer_expression
                    ok = verify_step_expression(da.answer_expression, step.expected_expr or "")
            if ok:
                session.extracted_answer = step.expected_expr

        if ok:
            return self._advance_step(session, t0)
        return self._fail_step(session, step, t0)

    def _advance_step(self, session: SessionState, t0: float) -> EngineResult:
        problem = session.current_problem
        steps = problem.tutoring_steps
        step = steps[session.step_walk.step_index]
        session.step_walk.step_index += 1
        session.step_walk.step_attempts = 0

        if session.step_walk.step_index >= len(steps):
            # walk complete: the final step was the answer
            session.step_walk = None
            session.app_state = AppState.POST_RESPONSE_OPTIONS
            spoken = self._polish(session, problem, self.responses.step_complete(step), {"step": step.question})
            session.last_spoken = spoken
            prog = session.session_progress
            from app.models.schemas import ProblemProgress
            pp = prog.by_problem.get(problem.problem_id) or ProblemProgress(problem_id=problem.problem_id)
            pp.attempts += 1
            pp.correct = True
            pp.resolved = True
            prog.by_problem[problem.problem_id] = pp
            prog.problems_attempted = len(prog.by_problem)
            prog.problems_correct = sum(1 for p in prog.by_problem.values() if p.correct)
            try:
                self._store_strength_memory(session, problem, structured_answer=step.expected_expr)
            except Exception as exc:
                log.warning("Strength memory store failed: %s", exc)
            self._refresh_actions(session)
            session.voice_status = VoiceStatus.SPEAKING
            return self._finish(session, spoken=spoken, t0=t0, events=[PipelineEvent(
                stage="response", label="Step walk completed", detail=spoken[:90])])

        next_step = steps[session.step_walk.step_index]
        spoken = self._polish(session, problem, self.responses.step_advance(step, next_step), {"step": next_step.question})
        session.app_state = AppState.REASONING
        session.last_spoken = spoken
        self._refresh_actions(session)
        session.voice_status = VoiceStatus.SPEAKING
        return self._finish(session, spoken=spoken, t0=t0, events=[PipelineEvent(
            stage="response", label="Next guided step", detail=spoken[:90])])

    def _fail_step(self, session: SessionState, step, t0: float) -> EngineResult:
        session.step_walk.step_attempts += 1
        if session.step_walk.step_attempts >= max(2, self.conf.max_attempts_before_solution):
            # repeated failure on one step -> full, verified solution (policy-aligned)
            return self._show_solution(session, t0)
        session.pending_confirmation = {"type": "step_hint"}
        spoken = self._polish(session, session.current_problem, self.responses.step_wrong_offer_hint(step), {"step": step.question})
        session.app_state = AppState.REASONING
        session.last_spoken = spoken
        self._refresh_actions(session)
        session.voice_status = VoiceStatus.SPEAKING
        return self._finish(session, spoken=spoken, t0=t0, events=[PipelineEvent(
            stage="response", label="Step hint offered", detail=spoken[:90], ok=False)])

    # ==================================================================
    # selection / navigation
    # ==================================================================
    def _select_option(self, session: SessionState, option: Optional[str], t0: float) -> EngineResult:
        if not option:
            return self._finish(session, spoken=self.responses.reprocess(session), error="missing option", t0=t0)

        state = session.app_state

        if state in (AppState.HOME, AppState.MODE_SELECTION):
            mode = self._match_mode(option)
            if mode is None:
                return self._finish(
                    session,
                    spoken=f"I didn't catch that mode. " + number_options(_MODES),
                    error="invalid mode",
                    t0=t0,
                )
            session.mode = mode
            if mode == LearningMode.REVIEW:
                session.app_state = AppState.REVIEW
                self._refresh_actions(session)
                spoken = self.responses.review_summary(session)
                session.last_spoken = spoken
                return self._finish(session, spoken=spoken, t0=t0)
            if self.conf.confirm_mode_selection and not session.pending_confirmation:
                session.pending_confirmation = {"type": "mode", "value": mode.value}
                session.app_state = AppState.MODE_SELECTION
                self._refresh_actions(session)
                bump(session)
                return self._finish(session, spoken=self.responses.confirm_mode(mode.value.title()), t0=t0)
            return self._enter_topic_selection(session, t0)

        if state == AppState.TOPIC_SELECTION:
            topics = list_topics()
            topic = self._match_list(option, topics)
            if topic is None:
                return self._finish(
                    session, spoken="Please choose one of the topics: " + number_options(topics),
                    error="invalid topic", t0=t0,
                )
            session.topic = topic
            session.app_state = AppState.SUBTOPIC_SELECTION
            self._refresh_actions(session)
            spoken = self.responses.ask_subtopic(session, list_subtopics(topic))
            session.last_spoken = spoken
            return self._finish(session, spoken=spoken, t0=t0)

        if state == AppState.SUBTOPIC_SELECTION:
            subtopics = list_subtopics(session.topic or "")
            sub = self._match_list(option, subtopics)
            if sub is None:
                return self._finish(
                    session, spoken="Please choose one of the subtopics: " + number_options(subtopics),
                    error="invalid subtopic", t0=t0,
                )
            session.subtopic = sub
            session.app_state = AppState.DIFFICULTY_SELECTION
            self._refresh_actions(session)
            spoken = self.responses.ask_difficulty(session)
            session.last_spoken = spoken
            return self._finish(session, spoken=spoken, t0=t0)

        if state == AppState.DIFFICULTY_SELECTION:
            diff = self._match_list(option, _DIFFICULTIES)
            if diff is None:
                return self._finish(
                    session, spoken="Please choose a difficulty: " + number_options(_DIFFICULTIES),
                    error="invalid difficulty", t0=t0,
                )
            session.difficulty = Difficulty(diff.lower())
            return self._present_problem(session, t0, exclude=[])

        if state == AppState.POST_RESPONSE_OPTIONS:
            return self._post_response_option(session, option, t0)

        if state == AppState.REVIEW:
            if "practice" in option.lower():
                return self._practice_more(session, t0)
            if "end" in option.lower():
                return self._end_session(session, t0)
            return self._finish(session, spoken=self.responses.reprocess(session), error="invalid review option", t0=t0)

        if state == AppState.END_SESSION:
            return self._start_new_session(session, t0)

        if state == AppState.INTERVENTION:
            low = option.lower()
            if low.startswith("try"):
                return self._try_again(session, t0)
            if "hint" in low:
                return self._give_hint(session, t0)
            if low.startswith("review"):
                return self._review_approach(session, t0)
            if "solution" in low or "answer" in low:
                return self._show_solution(session, t0)
            if low.startswith("next"):
                return self._next_problem(session, t0)

        return self._finish(session, spoken=self.responses.reprocess(session), error="option not valid here", t0=t0)

    # ------------------------------------------------------------------
    def _post_response_option(self, session: SessionState, option: str, t0: float) -> EngineResult:
        low = option.lower()
        if low.startswith("next"):
            return self._next_problem(session, t0)
        if "review" in low or "review session" in low:
            session.app_state = AppState.REVIEW
            self._refresh_actions(session)
            spoken = self.responses.review_summary(session)
            session.last_spoken = spoken
            return self._finish(session, spoken=spoken, t0=t0)
        if low.startswith("end") or "finish" in low:
            return self._end_session(session, t0)
        if low.startswith("try"):
            return self._try_again(session, t0)
        if low.startswith("practice"):
            return self._practice_more(session, t0)
        return self._finish(session, spoken=self.responses.reprocess(session), error="invalid post-response option", t0=t0)

    def _confirm(self, session: SessionState, yes: bool, t0: float) -> EngineResult:
        pending = session.pending_confirmation
        if not pending:
            return self._finish(session, spoken=self.responses.reprocess(session), error="nothing to confirm", t0=t0)
        # guided step walk: "Would you like a hint?" -> yes/no
        if pending.get("type") == "step_hint":
            session.pending_confirmation = None
            problem = session.current_problem
            if yes and problem and problem.tutoring_steps and session.step_walk:
                idx = session.step_walk.step_index
                if 0 <= idx < len(problem.tutoring_steps):
                    step = problem.tutoring_steps[idx]
                    session.step_walk.step_attempts = 0
                    spoken = self.responses.step_hint(step)
                    session.app_state = AppState.REASONING
                    session.last_spoken = spoken
                    self._refresh_actions(session)
                    return self._finish(session, spoken=spoken, t0=t0)
            if problem and problem.tutoring_steps and session.step_walk:
                idx = session.step_walk.step_index
                if 0 <= idx < len(problem.tutoring_steps):
                    step = problem.tutoring_steps[idx]
                    spoken = step.question
                    session.app_state = AppState.REASONING
                    session.last_spoken = spoken
                    self._refresh_actions(session)
                    return self._finish(session, spoken=spoken, t0=t0)
            return self._finish(session, spoken=self._prompt_for(session), t0=t0)
        if not yes:
            session.pending_confirmation = None
            session.mode = None
            session.app_state = AppState.MODE_SELECTION
            self._refresh_actions(session)
            bump(session)
            return self._finish(session, spoken="No problem. " + self.responses.welcome(session), t0=t0)
        session.pending_confirmation = None
        if pending.get("type") == "mode":
            return self._enter_topic_selection(session, t0)
        return self._finish(session, spoken=self.responses.reprocess(session), t0=t0)

    def _enter_topic_selection(self, session: SessionState, t0: float) -> EngineResult:
        session.app_state = AppState.TOPIC_SELECTION
        self._refresh_actions(session)
        spoken = self.responses.ask_topic(session, list_topics())
        session.last_spoken = spoken
        return self._finish(session, spoken=spoken, t0=t0)

    def _practice_more(self, session: SessionState, t0: float) -> EngineResult:
        session.app_state = AppState.TOPIC_SELECTION
        self._refresh_actions(session)
        spoken = self.responses.ask_topic(session, list_topics())
        session.last_spoken = spoken
        return self._finish(session, spoken=spoken, t0=t0)

    def _start_new_session(self, session: SessionState, t0: float) -> EngineResult:
        new_session = self.sessions.get_or_create(session.student_id, force_new=True)
        return self.start_session(new_session)

    def _end_session(self, session: SessionState, t0: float) -> EngineResult:
        session.app_state = AppState.END_SESSION
        self._refresh_actions(session)
        spoken = self.responses.end_summary(session)
        session.last_spoken = spoken
        return self._finish(session, spoken=spoken, t0=t0)

    # ==================================================================
    # problem lifecycle
    # ==================================================================
    def _present_problem(self, session: SessionState, t0: float, exclude: Optional[List[str]] = None) -> EngineResult:
        exclude = list(exclude or [])
        # Persistent learner memory drives problem selection: never repeat a
        # problem the student has already attempted (across sessions).
        try:
            for rec in self.memory.list_for_student(session.student_id):
                if rec.problem_id and rec.problem_id not in exclude:
                    exclude.append(rec.problem_id)
        except Exception as exc:
            log.warning("Memory lookup for problem selection failed: %s", exc)
        problem = find_problem(
            session.topic or "", session.subtopic or "", session.difficulty or Difficulty.EASY, exclude
        )
        if problem is None:
            return self._finish(
                session,
                spoken="I couldn't find a problem for that selection. Let's go back and choose again.",
                error="no problem found",
                t0=t0,
            )
        session.current_problem = problem
        session.current_attempt = 0
        session.assistance_level = AssistanceLevel.INDEPENDENT
        session.structured_reasoning = None
        session.verification_result = None
        session.misconception = None
        session.selected_intervention = None
        session.reasoning_transcript = ""
        session.step_walk = None
        session.pending_confirmation = None
        session.input_type = None
        session.extracted_answer = None
        session.app_state = AppState.REASONING
        self._refresh_actions(session)
        spoken = self.responses.present_problem(session, problem)
        session.last_spoken = spoken
        return self._finish(session, spoken=spoken, t0=t0)

    def _next_problem(self, session: SessionState, t0: float) -> EngineResult:
        problem = session.current_problem
        exclude = []
        prog = session.session_progress
        if problem:
            exclude = list(prog.by_problem.keys())
            if problem.problem_id in exclude:
                exclude.remove(problem.problem_id)
            next_p = related_problem(problem, exclude=exclude)
            if next_p:
                session.current_problem = next_p
                session.current_attempt = 0
                session.assistance_level = AssistanceLevel.INDEPENDENT
                session.structured_reasoning = None
                session.verification_result = None
                session.misconception = None
                session.selected_intervention = None
                session.reasoning_transcript = ""
                session.step_walk = None
                session.pending_confirmation = None
                session.input_type = None
                session.extracted_answer = None
                session.app_state = AppState.REASONING
                self._refresh_actions(session)
                spoken = self.responses.present_problem(session, next_p)
                session.last_spoken = spoken
                return self._finish(session, spoken=spoken, t0=t0)
        # no related problem: go back to topic selection
        session.app_state = AppState.TOPIC_SELECTION
        session.step_walk = None
        self._refresh_actions(session)
        spoken = self.responses.ask_topic(session, list_topics())
        session.last_spoken = spoken
        return self._finish(session, spoken=spoken, t0=t0)

    def _try_again(self, session: SessionState, t0: float) -> EngineResult:
        if session.current_problem is None:
            return self._select_option(session, "Practice", t0)
        # inside a step walk: re-ask the current step question
        if session.step_walk and session.current_problem.tutoring_steps:
            idx = session.step_walk.step_index
            if 0 <= idx < len(session.current_problem.tutoring_steps):
                session.step_walk.step_attempts = 0
                session.pending_confirmation = None
                step = session.current_problem.tutoring_steps[idx]
                spoken = step.question
                session.app_state = AppState.REASONING
                session.last_spoken = spoken
                self._refresh_actions(session)
                return self._finish(session, spoken=spoken, t0=t0)
        session.app_state = AppState.REASONING
        self._refresh_actions(session)
        spoken = self.responses.reasoning_prompt(session, session.current_attempt + 1)
        session.last_spoken = spoken
        return self._finish(session, spoken=spoken, t0=t0)

    def _give_hint(self, session: SessionState, t0: float) -> EngineResult:
        problem = session.current_problem
        if problem is None:
            return self._finish(session, spoken=self.responses.reprocess(session), error="no active problem", t0=t0)
        if session.mode == LearningMode.TEST:
            return self._finish(
                session,
                spoken="This is a test, so I can't give hints. Try your best, then say next problem.",
                t0=t0,
            )
        # inside a step walk: give the hint for the current step
        if session.step_walk and problem.tutoring_steps:
            idx = session.step_walk.step_index
            if 0 <= idx < len(problem.tutoring_steps):
                step = problem.tutoring_steps[idx]
                session.pending_confirmation = None
                spoken = self.responses.step_hint(step)
                session.last_spoken = spoken
                session.app_state = AppState.REASONING
                self._refresh_actions(session)
                return self._finish(session, spoken=spoken, t0=t0)
        level = max(session.assistance_level, AssistanceLevel.HINT)
        session.assistance_level = level
        session.session_progress.hints_used += 1
        prog = session.session_progress.by_problem.get(problem.problem_id)
        if prog:
            prog.hints_used += 1
        spoken = self.responses.hint_response(problem, level, session.misconception)
        session.last_spoken = spoken
        # after a hint the student should attempt the reasoning again
        session.app_state = AppState.REASONING
        self._refresh_actions(session)
        return self._finish(session, spoken=spoken, t0=t0)

    def _review_approach(self, session: SessionState, t0: float) -> EngineResult:
        problem = session.current_problem
        if problem is None:
            return self._finish(session, spoken=self.responses.reprocess(session), error="no active problem", t0=t0)
        session.assistance_level = max(session.assistance_level, AssistanceLevel.REVIEW_APPROACH)
        spoken = self.responses.review_response(problem, session.misconception)
        session.last_spoken = spoken
        session.app_state = AppState.REASONING
        self._refresh_actions(session)
        return self._finish(session, spoken=spoken, t0=t0)

    def _show_solution(self, session: SessionState, t0: float) -> EngineResult:
        problem = session.current_problem
        if problem is None:
            return self._finish(session, spoken=self.responses.reprocess(session), error="no active problem", t0=t0)
        session.step_walk = None
        session.pending_confirmation = None
        session.assistance_level = AssistanceLevel.DETAILED_SOLUTION
        prog = session.session_progress.by_problem.get(problem.problem_id)
        if prog:
            prog.resolved = True
        spoken = self.responses.solution_response(problem)
        session.last_spoken = spoken
        session.app_state = AppState.POST_RESPONSE_OPTIONS
        self._refresh_actions(session)
        return self._finish(session, spoken=spoken, t0=t0)

    # ==================================================================
    # the reasoning pipeline
    # ==================================================================
    def _run_reasoning_pipeline(
        self, session: SessionState, transcript: str, t0: float,
        pre_events: Optional[List[PipelineEvent]] = None,
    ) -> EngineResult:
        problem = session.current_problem
        if problem is None:
            return self._finish(session, spoken=self.responses.reprocess(session), error="no active problem", t0=t0)

        events: List[PipelineEvent] = list(pre_events or [])
        session.current_attempt += 1
        session.reasoning_transcript = transcript
        session.extracted_answer = None

        # 1. STT (already happened in the browser; transcript is the result)
        events.append(PipelineEvent(stage="stt", label="Speech recognized", detail=transcript[:120], t_ms=1))

        # 2. Reasoning interpretation
        structured = self.interpreter.interpret(problem, transcript)
        events.append(PipelineEvent(
            stage="interpreter",
            label="Reasoning interpreted",
            detail=f"{len(structured.mathematical_claims)} claims, pattern: {structured.reasoning_pattern[:60]}",
            ok=len(structured.mathematical_claims) > 0,
        ))
        return self._complete_pipeline(session, problem, structured, transcript, events, t0, from_direct=False)

    # ------------------------------------------------------------------
    def _complete_pipeline(
        self, session, problem, structured, transcript, events, t0,
        from_direct: bool = False, pre_events: Optional[List[PipelineEvent]] = None,
    ) -> EngineResult:
        if pre_events:
            events = list(pre_events) + events

        # 3. Deterministic verification (SymPy)
        verification = verify(structured, problem)
        events.append(PipelineEvent(
            stage="verifier",
            label="Mathematics verified (SymPy)",
            detail=f"verdict={verification.verdict.value}, final_correct={verification.final_answer_correct}",
        ))

        # 4. Misconception detection
        misconception = self.detector.detect(problem, structured, verification)
        events.append(PipelineEvent(
            stage="misconception",
            label="Diagnosis complete",
            detail=misconception.misconception_type if misconception.detected else "no misconception detected",
            ok=misconception.detected,
        ))

        # 5. Qdrant learner-memory retrieval
        memories = []
        try:
            memories = self.memory.retrieve_relevant_memories(
                session.student_id,
                query_text=transcript,
                concept=structured.concept,
                limit=5,
            )
        except Exception as exc:
            log.warning("Memory retrieval failed: %s", exc)
            events.append(PipelineEvent(stage="memory", label="Memory unavailable", detail=str(exc)[:80], ok=False))
        else:
            events.append(PipelineEvent(
                stage="memory",
                label=f"Memory retrieved ({self.memory.provider})",
                detail=f"{len(memories)} relevant records",
            ))

        # 6. Adaptive tutoring policy
        intervention = self.policy.select_intervention(
            problem=problem,
            structured=structured,
            verification=verification,
            misconception=misconception,
            attempt_count=session.current_attempt,
            hints_used=session.session_progress.hints_used,
            previous_intervention=session.selected_intervention,
            retrieved_memories=memories,
            mode=session.mode,
            difficulty=session.difficulty,
        )
        events.append(PipelineEvent(
            stage="policy",
            label="Tutoring policy applied",
            detail=intervention.type.value + (" · memory-based" if intervention.memory_based else ""),
        ))

        # 7. Persist learner memories (misconception, attempt, strength)
        try:
            self._store_memories(session, problem, structured, verification, misconception)
        except Exception as exc:
            log.warning("Memory storage failed: %s", exc)
            events.append(PipelineEvent(stage="memory", label="Memory store failed", detail=str(exc)[:80], ok=False))

        # 8. Response + state transition
        correct = verification.verdict == Verdict.CORRECT
        session.structured_reasoning = structured
        session.verification_result = verification
        session.misconception = misconception
        session.retrieved_memories = memories
        session.selected_intervention = intervention
        session.assistance_level = intervention.assistance_level

        if verification.verdict == Verdict.CORRECT:
            if from_direct:
                spoken = (
                    self.responses.direct_correct(problem)
                    + " What would you like to do next? "
                    + number_options(intervention.next_actions)
                )
            else:
                spoken = self.responses.diagnosis_response(problem, structured, verification, misconception, intervention)
            session.app_state = AppState.POST_RESPONSE_OPTIONS
        elif verification.verdict == Verdict.AMBIGUOUS:
            spoken = self.responses.ambiguous_response(intervention)
            session.app_state = AppState.REASONING
        elif verification.verdict == Verdict.INCOMPLETE:
            spoken = self.responses.incomplete_response(problem, structured, intervention)
            session.app_state = AppState.INTERVENTION
        else:
            # INCORRECT: a wrong short answer enters the guided step walk when available
            if (
                from_direct
                and not misconception.correct_answer_trap
                and problem.tutoring_steps
                and session.mode != LearningMode.TEST
            ):
                self._record_attempt(session, problem, transcript, structured, verification, misconception, intervention, False, t0)
                return self._enter_step_walk(session, problem, structured, verification, misconception, intervention, events, t0)
            spoken = self.responses.diagnosis_response(problem, structured, verification, misconception, intervention)
            session.app_state = AppState.INTERVENTION

        self._record_attempt(session, problem, transcript, structured, verification, misconception, intervention, correct, t0)

        spoken = self._polish(session, problem, spoken)
        events.append(PipelineEvent(stage="response", label="Response generated", detail=spoken[:90]))

        session.last_spoken = spoken
        session.last_pipeline_events = events
        self._refresh_actions(session)
        session.voice_status = VoiceStatus.SPEAKING
        return EngineResult(session, spoken=spoken, events=events, latency_ms=int((time.perf_counter() - t0) * 1000))

    # ------------------------------------------------------------------
    def _corrected_misconception_type(self, session: SessionState) -> Optional[str]:
        """Return the misconception type a CORRECT re-attempt has just revised.

        A genuine self-correction means the result still carried on the session
        from the immediately preceding attempt of THIS problem (the pipeline
        replaces those fields only after memory storage) was non-correct and was
        diagnosed with a misconception — and the full solution had not been
        revealed in between (assistance stayed below DETAILED_SOLUTION) and no
        guided step walk is in progress.
        """
        prev_verification = session.verification_result
        prev_misconception = session.misconception
        if prev_verification is None or prev_misconception is None or not prev_misconception.detected:
            return None
        if prev_verification.verdict not in (Verdict.INCORRECT, Verdict.INCOMPLETE):
            return None
        if session.assistance_level >= AssistanceLevel.DETAILED_SOLUTION:
            return None  # the solution was already shown; not an independent correction
        if session.step_walk is not None:
            return None  # mid-walk turns are guided step answers, not self-corrections
        return prev_misconception.misconception_type or None

    # ------------------------------------------------------------------
    def _store_memories(self, session, problem, structured, verification, misconception) -> None:
        # self-correction: this verified-correct attempt revises an earlier wrong,
        # misconception-diagnosed attempt on the same problem. Logged as its own
        # distinct memory event (never merged into the misconception record) so it
        # is retrievable the same way misconception memories are.
        if verification.verdict == Verdict.CORRECT:
            corrected_type = self._corrected_misconception_type(session)
            if corrected_type:
                self.memory.store_memory(
                    student_id=session.student_id,
                    session_id=session.session_id,
                    problem_id=problem.problem_id,
                    source_session=f"session-{session.session_number}",
                    concept=structured.concept or problem.subtopic,
                    topic=problem.topic,
                    subtopic=problem.subtopic,
                    memory_type=MemoryType.SELF_CORRECTION,
                    description=(
                        f"Self-corrected on {problem.problem_id}: revised an earlier "
                        f"{corrected_type} mistake into a verified solution."
                    ),
                    evidence=(
                        f"corrected={corrected_type}, "
                        f"earlier_verdict={session.verification_result.verdict.value if session.verification_result else 'n/a'}"
                    ),
                    confidence=0.95,
                    metadata={"misconception_type": corrected_type},
                )
        # misconception memory (deduplicated by the memory service)
        if misconception.detected:
            self.memory.store_memory(
                student_id=session.student_id,
                session_id=session.session_id,
                problem_id=problem.problem_id,
                source_session=f"session-{session.session_number}",
                concept=structured.concept or problem.subtopic,
                topic=problem.topic,
                subtopic=problem.subtopic,
                memory_type=MemoryType.MISCONCEPTION,
                description=misconception.recommended_intervention or misconception.evidence,
                evidence=misconception.evidence,
                confidence=misconception.confidence,
                metadata={
                    "misconception_type": misconception.misconception_type,
                    "correct_answer_trap": misconception.correct_answer_trap,
                    "frequency": 1,
                },
            )
        # attempt / learning evidence
        self.memory.store_memory(
            student_id=session.student_id,
            session_id=session.session_id,
            problem_id=problem.problem_id,
            source_session=f"session-{session.session_number}",
            concept=structured.concept or problem.subtopic,
            topic=problem.topic,
            subtopic=problem.subtopic,
            memory_type=MemoryType.ATTEMPT,
            description=f"Attempt {session.current_attempt}: {structured.raw_transcript[:140]}",
            evidence=f"verdict={verification.verdict.value}, answer={structured.final_answer}",
            confidence=structured.confidence,
            metadata={
                "verdict": verification.verdict.value,
                "final_answer": structured.final_answer,
                "hints_used": session.session_progress.hints_used,
            },
        )
        # strength memory + resolve previous misconception on success
        if verification.verdict == Verdict.CORRECT:
            self._store_strength_memory(session, problem, structured_answer=structured.final_answer)

    # ------------------------------------------------------------------
    def _store_strength_memory(self, session, problem, structured_answer) -> None:
        self.memory.store_memory(
            student_id=session.student_id,
            session_id=session.session_id,
            problem_id=problem.problem_id,
            source_session=f"session-{session.session_number}",
            concept=problem.concepts[0] if problem.concepts else problem.subtopic.lower().replace(" ", "_"),
            topic=problem.topic,
            subtopic=problem.subtopic,
            memory_type=MemoryType.STRENGTH,
            description=f"Solved {problem.problem_id} correctly with sound reasoning.",
            evidence=f"answer={structured_answer}",
            confidence=0.95,
            metadata={"difficulty": problem.difficulty.value},
        )
        # resolve matching active misconception memories from PREVIOUS sessions
        # (mastery demonstrated across sessions -> the memory is retired).
        concept = problem.concepts[0] if problem.concepts else problem.subtopic.lower().replace(" ", "_")
        for mem in self.memory.retrieve_relevant_memories(
            session.student_id, query_text=problem.prompt, concept=concept, limit=10
        ):
            if (
                mem.memory_type == MemoryType.MISCONCEPTION
                and mem.status.value == "active"
                and mem.concept == concept
                and mem.session_id != session.session_id
            ):
                self.memory.mark_memory_resolved(mem.memory_id)

    # ------------------------------------------------------------------
    def _record_attempt(self, session, problem, transcript, structured, verification, misconception, intervention, correct, t0) -> None:
        prog = session.session_progress
        prog.total_attempts += 1
        from app.models.schemas import ProblemProgress

        pp = prog.by_problem.get(problem.problem_id) or ProblemProgress(problem_id=problem.problem_id)
        pp.attempts += 1
        if correct:
            pp.correct = True
            pp.resolved = True
        prog.by_problem[problem.problem_id] = pp
        prog.problems_attempted = len(prog.by_problem)
        prog.problems_correct = sum(1 for p in prog.by_problem.values() if p.correct)

    # ==================================================================
    # helpers
    # ==================================================================
    def _response_context(self, session: SessionState, problem: Optional[Problem], spoken: str, extra: Optional[dict] = None) -> dict:
        """Structured context handed to the LLM for natural response wording."""
        ctx = {
            "problem": problem.prompt if problem else "",
            "student_input": session.reasoning_transcript or "",
            "input_type": session.input_type or "",
            "verification": session.verification_result.verdict.value if session.verification_result else "",
            "misconception": session.misconception.misconception_type
            if session.misconception and session.misconception.detected else "",
            "learner_memory": len(session.retrieved_memories or []),
            "assistance_level": session.assistance_level.value,
            "tutoring_strategy": session.selected_intervention.type.value
            if session.selected_intervention else "",
            "conversation_context": [t.text for t in (session.turns or [])[-6:]],
            "deterministic_message": spoken,
        }
        if extra:
            ctx.update(extra)
        return ctx

    def _polish(self, session: SessionState, problem: Optional[Problem], spoken: str, extra: Optional[dict] = None) -> str:
        """Gemma may reword a tutor response; the deterministic message is the fallback."""
        if not (self.llm and self.llm.is_configured and getattr(self.llm, "use_for_responses", True)):
            return spoken
        try:
            polished = self.llm.generate_response(self._response_context(session, problem, spoken, extra))
            if polished and polished.strip():
                return polished.strip()
        except Exception as exc:
            log.warning("Response polish failed (%s) — using deterministic message.", exc)
        return spoken

    def _finish(self, session: SessionState, *, spoken: str, t0: float, error: str = "", events=None) -> EngineResult:
        if spoken:
            session.last_spoken = spoken
        session.voice_status = VoiceStatus.SPEAKING
        if error:
            session.last_error = error
        bump(session)
        latency = int((time.perf_counter() - t0) * 1000)
        return EngineResult(session, spoken=spoken, events=events or [], ok=not error, error=error, latency_ms=latency)

    def _refresh_actions(self, session: SessionState) -> None:
        actions = compute_available_actions(session)
        if session.app_state == AppState.TOPIC_SELECTION:
            actions = list_topics()
        elif session.app_state == AppState.SUBTOPIC_SELECTION:
            actions = list_subtopics(session.topic or "")
        elif session.app_state == AppState.HOME or session.app_state == AppState.MODE_SELECTION:
            actions = list(_MODES)
        elif session.app_state == AppState.DIFFICULTY_SELECTION:
            actions = list(_DIFFICULTIES)
        elif session.app_state == AppState.REVIEW:
            actions = ["Practice more", "End session"]
        elif session.app_state == AppState.END_SESSION:
            actions = ["Start a new session"]
        elif session.step_walk and session.app_state in (AppState.REASONING, AppState.INTERVENTION):
            actions = ["Hint", "Show the solution"]
        session.available_actions = actions

    def _prompt_for(self, session: SessionState) -> str:
        state = session.app_state
        if state == AppState.TOPIC_SELECTION:
            return self.responses.ask_topic(session, list_topics())
        if state == AppState.SUBTOPIC_SELECTION:
            return self.responses.ask_subtopic(session, list_subtopics(session.topic or ""))
        if state == AppState.DIFFICULTY_SELECTION:
            return self.responses.ask_difficulty(session)
        if state == AppState.REASONING:
            return self.responses.reasoning_prompt(session, session.current_attempt + 1)
        if state == AppState.REVIEW:
            return self.responses.review_summary(session)
        if state == AppState.END_SESSION:
            return self.responses.end_summary(session)
        if state == AppState.POST_RESPONSE_OPTIONS:
            return self.responses.post_response_options(session)
        return self.responses.welcome(session)

    def _clear_problem_context(self, session: SessionState) -> None:
        session.current_problem = None
        session.current_attempt = 0
        session.structured_reasoning = None
        session.verification_result = None
        session.misconception = None
        session.selected_intervention = None
        session.reasoning_transcript = ""
        session.step_walk = None
        session.pending_confirmation = None
        session.input_type = None
        session.extracted_answer = None

    @staticmethod
    def _match_mode(option: str) -> Optional[LearningMode]:
        low = option.lower().strip()
        for m in LearningMode:
            if m.value in low or (m.name.lower() in low and len(low) <= 12):
                return m
        if "test" in low or "exam" in low:
            return LearningMode.TEST
        return None

    @staticmethod
    def _match_list(option: str, choices: List[str]) -> Optional[str]:
        low = option.lower().strip()
        for c in choices:
            cl = c.lower()
            if cl == low or low.startswith(cl) or cl.startswith(low):
                return c
        for c in choices:
            if any(w in low for w in c.lower().split()):
                return c
        return None
