"""Shared pydantic models for MathTalk.

This module is the single contract between the voice interface, the visual
dashboard, the reasoning pipeline and the tutoring engine. There is no
separate state or logic for voice vs. visual operation.
"""
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------
class AppState(str, Enum):
    HOME = "HOME"
    MODE_SELECTION = "MODE_SELECTION"
    TOPIC_SELECTION = "TOPIC_SELECTION"
    SUBTOPIC_SELECTION = "SUBTOPIC_SELECTION"
    DIFFICULTY_SELECTION = "DIFFICULTY_SELECTION"
    PROBLEM_PRESENTATION = "PROBLEM_PRESENTATION"
    REASONING = "REASONING"
    DIAGNOSIS = "DIAGNOSIS"  # transient: pipeline computing the diagnosis
    INTERVENTION = "INTERVENTION"
    POST_RESPONSE_OPTIONS = "POST_RESPONSE_OPTIONS"
    NEXT_PROBLEM = "NEXT_PROBLEM"  # transient: engine picks the next problem
    REVIEW = "REVIEW"
    ERROR_RECOVERY = "ERROR_RECOVERY"
    END_SESSION = "END_SESSION"


class LearningMode(str, Enum):
    LEARN = "learn"
    PRACTICE = "practice"
    TEST = "test"
    REVIEW = "review"


class Difficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class VoiceStatus(str, Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    PROCESSING = "PROCESSING"
    SPEAKING = "SPEAKING"
    ERROR = "ERROR"


class ClaimStatus(str, Enum):
    VERIFIED = "verified"
    CONTRADICTED = "contradicted"
    UNCERTAIN = "uncertain"
    UNSUPPORTED = "unsupported"


class Verdict(str, Enum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    INCOMPLETE = "incomplete"
    AMBIGUOUS = "ambiguous"


class MemoryType(str, Enum):
    MISCONCEPTION = "misconception"
    REASONING_PATTERN = "reasoning_pattern"
    SUCCESSFUL_INTERVENTION = "successful_intervention"
    ATTEMPT = "attempt"
    STRENGTH = "strength"
    PROGRESS = "progress"
    ASSESSMENT = "assessment"
    # A student revised an earlier wrong, misconception-diagnosed attempt into a
    # verified correct one on the same problem — logged as its own event so it is
    # never merged into (or mistaken for) a generic misconception occurrence.
    SELF_CORRECTION = "self_correction"


class MemoryStatus(str, Enum):
    ACTIVE = "active"
    RESOLVED = "resolved"


class AssistanceLevel(int, Enum):
    INDEPENDENT = 0
    REVIEW_APPROACH = 1
    HINT = 2
    GUIDED_EXPLANATION = 3
    DETAILED_SOLUTION = 4


class InputType(str, Enum):
    """Contextual classification of a student utterance."""

    COMMAND = "COMMAND"
    DIRECT_ANSWER = "DIRECT_ANSWER"
    REASONING = "REASONING"
    QUESTION = "QUESTION"
    REQUEST_FOR_HELP = "REQUEST_FOR_HELP"
    REQUEST_FOR_HINT = "REQUEST_FOR_HINT"
    REQUEST_FOR_REPEAT = "REQUEST_FOR_REPEAT"
    CONFIRMATION = "CONFIRMATION"
    REJECTION = "REJECTION"
    UNCERTAIN = "UNCERTAIN"
    OTHER = "OTHER"


class InterventionType(str, Enum):
    PRAISE_AND_NEXT = "praise_and_next"
    CORRECT_ANSWER_FLAWED_REASONING = "correct_answer_flawed_reasoning"
    TARGETED_INTERVENTION = "targeted_intervention"
    GENERIC_INTERVENTION = "generic_intervention"
    HINT = "hint"
    REVIEW_APPROACH = "review_approach"
    GUIDED_EXPLANATION = "guided_explanation"
    DETAILED_SOLUTION = "detailed_solution"
    ENCOURAGE_CONTINUE = "encourage_continue"
    REPROMPT = "reprompt"


class IntentKind(str, Enum):
    SELECT_OPTION = "select_option"
    CONFIRM_YES = "confirm_yes"
    CONFIRM_NO = "confirm_no"
    SUBMIT_REASONING = "submit_reasoning"
    REQUEST_HINT = "request_hint"
    REVIEW_APPROACH = "review_approach"
    TRY_AGAIN = "try_again"
    SHOW_SOLUTION = "show_solution"
    NEXT_PROBLEM = "next_problem"
    PRACTICE_MORE = "practice_more"
    START_NEW_SESSION = "start_new_session"
    HELP = "help"
    REPEAT = "repeat"
    GO_BACK = "go_back"
    GO_HOME = "go_home"
    STOP = "stop"
    RESUME = "resume"
    END_SESSION = "end_session"
    UNKNOWN = "unknown"


# --------------------------------------------------------------------------
# Input understanding
# --------------------------------------------------------------------------
class DirectAnswer(BaseModel):
    """A short direct answer extracted from student speech."""

    input_type: InputType = InputType.DIRECT_ANSWER
    answer_expression: str = ""  # canonical/sympy-parseable expression, e.g. "4", "3/4", "5*x"
    answer_variable: Optional[str] = None  # e.g. "x" when the student says "x equals four"
    operation: Optional[str] = None  # set for guided step responses ("subtract")
    confidence: float = 0.0
    source: str = "deterministic"  # deterministic | llm
    raw_text: str = ""


class InputClassification(BaseModel):
    """Contextual interpretation of what the student meant."""

    input_type: InputType = InputType.OTHER
    direct_answer: Optional[DirectAnswer] = None
    confidence: float = 0.0
    source: str = "deterministic"  # deterministic | llm | llm+deterministic
    reason: str = ""


# --------------------------------------------------------------------------
# Guided step tutoring (smallest-useful-intervention walkthrough)
# --------------------------------------------------------------------------
class TutoringStep(BaseModel):
    """One guided question in a step-focused walk after a wrong answer."""

    step_id: str
    question: str  # spoken question, e.g. "What should we do with the 6?"
    expected_op: Optional[str] = None  # operation step: add|subtract|multiply|divide
    op_accept: List[str] = Field(default_factory=list)  # extra accepted synonyms
    expected_expr: Optional[str] = None  # computation step: sympy-parseable result
    hint: str = ""  # the smallest useful hint for THIS step
    confirm: str = "Exactly."  # spoken confirmation on a correct step response


class StepWalk(BaseModel):
    """Runtime state of an in-progress guided step walk."""

    problem_id: str
    step_index: int = 0
    step_attempts: int = 0
    total_steps: int = 0
    started_from: str = "wrong_answer"  # wrong_answer | stuck | review


# --------------------------------------------------------------------------
# Mathematics
# --------------------------------------------------------------------------
class Problem(BaseModel):
    problem_id: str
    topic: str
    subtopic: str
    difficulty: Difficulty
    prompt: str  # spoken / displayed prompt
    display: str = ""  # optional visual math (LaTeX-ish) representation
    expected_answer: str
    answer_expr: str  # sympy-parsable expected answer, e.g. "4" or "x = 4"
    solution_steps: List[str]
    concepts: List[str]
    common_misconceptions: List[str]
    unit: Optional[str] = None  # optional spoken unit for the answer
    tutoring_steps: List[TutoringStep] = Field(default_factory=list)  # step walk
    # natural, spoken phrasing used to ask for the answer
    ask_question: str = ""  # e.g. "What is x?" — falls back to prompt when empty


class MathClaim(BaseModel):
    """A single structured mathematical claim extracted from student speech."""

    text: str  # human readable, e.g. "6 + 14 = 20"
    operation: Optional[str] = None  # add / subtract / multiply / divide / solve / evaluate
    expression: Optional[str] = None  # sympy parsable left-hand side
    expected: Optional[str] = None  # sympy parsable right-hand side / target
    computed: Optional[str] = None  # deterministically computed value of the expression
    status: ClaimStatus = ClaimStatus.UNSUPPORTED
    reason: str = ""
    confidence: float = 0.0


class VerificationResult(BaseModel):
    """Deterministic (SymPy) verification of the student's reasoning."""

    claims: List[MathClaim] = Field(default_factory=list)
    student_answer: Optional[str] = None
    expected_answer: str = ""
    final_answer_correct: Optional[bool] = None
    plan_valid: Optional[bool] = None
    verdict: Verdict = Verdict.AMBIGUOUS
    correct_solution: str = ""
    reason: str = ""


class StructuredReasoning(BaseModel):
    """Interpreter output — structured representation of the student's reasoning."""

    concept: str = ""
    student_actions: List[str] = Field(default_factory=list)
    reasoning_pattern: str = ""
    mathematical_claims: List[MathClaim] = Field(default_factory=list)
    steps: List[str] = Field(default_factory=list)
    incorrect_steps: List[str] = Field(default_factory=list)
    final_answer: Optional[str] = None
    reasoning_quality: str = ""  # "sound" | "flawed" | "incomplete" | "ambiguous"
    confidence: float = 0.0
    raw_transcript: str = ""
    source: str = "deterministic"  # deterministic | llm | llm+deterministic


class Misconception(BaseModel):
    detected: bool = False
    concept: str = ""
    misconception_type: str = ""  # e.g. "inverse_operation"
    evidence: str = ""
    affected_step: str = ""
    confidence: float = 0.0
    recommended_intervention: str = ""
    # True when the final answer was right but the reasoning was flawed
    correct_answer_trap: bool = False


class Intervention(BaseModel):
    type: InterventionType = InterventionType.GENERIC_INTERVENTION
    assistance_level: AssistanceLevel = AssistanceLevel.INDEPENDENT
    message: str = ""
    targeted: bool = False
    memory_based: bool = False
    next_actions: List[str] = Field(default_factory=list)
    reason: str = ""
    memory_ids_to_resolve: List[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Memory
# --------------------------------------------------------------------------
class MemoryRecord(BaseModel):
    memory_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    student_id: str
    session_id: str = ""
    problem_id: str = ""
    source_session: str = ""
    concept: str = ""
    topic: str = ""
    subtopic: str = ""
    memory_type: MemoryType = MemoryType.ATTEMPT
    description: str = ""
    evidence: str = ""
    confidence: float = 0.0
    timestamp: float = Field(default_factory=time.time)
    status: MemoryStatus = MemoryStatus.ACTIVE
    metadata: Dict[str, Any] = Field(default_factory=dict)
    score: Optional[float] = None  # retrieval similarity, set on retrieval


class TimelineEntry(BaseModel):
    """One past occurrence of a misconception type, for the memory timeline.

    Read-only view built from stored MemoryRecords (never written back).
    """

    session_id: str = ""
    problem_id: str = ""
    label: str = ""  # short human-readable misconception label
    memory_type: str = ""  # misconception | self_correction
    response_kind: str = ""  # generic | targeted | self_correction
    timestamp: float = 0.0
    detail: str = ""


# --------------------------------------------------------------------------
# Pipeline events (for the visual dashboard)
# --------------------------------------------------------------------------
class PipelineEvent(BaseModel):
    stage: str  # stt | interpreter | verifier | misconception | memory | policy | response
    label: str
    detail: str = ""
    ok: bool = True
    t_ms: int = 0


# --------------------------------------------------------------------------
# Attempts / progress
# --------------------------------------------------------------------------
class AttemptRecord(BaseModel):
    attempt_number: int
    transcript: str = ""
    structured_reasoning: Optional[StructuredReasoning] = None
    verification: Optional[VerificationResult] = None
    misconception: Optional[Misconception] = None
    intervention: Optional[Intervention] = None
    assistance_level: AssistanceLevel = AssistanceLevel.INDEPENDENT
    correct: bool = False
    t_ms: int = 0


class ProblemProgress(BaseModel):
    problem_id: str
    attempts: int = 0
    correct: bool = False
    hints_used: int = 0
    resolved: bool = False


class SessionProgress(BaseModel):
    problems_attempted: int = 0
    problems_correct: int = 0
    total_attempts: int = 0
    hints_used: int = 0
    by_problem: Dict[str, ProblemProgress] = Field(default_factory=dict)


# --------------------------------------------------------------------------
# Central session state (single source of truth)
# --------------------------------------------------------------------------
class TurnRecord(BaseModel):
    speaker: str  # "system" | "student"
    text: str
    intent: Optional[str] = None
    t: float = Field(default_factory=time.time)


class SessionState(BaseModel):
    student_id: str = "student"
    session_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    session_number: int = 1
    app_state: AppState = AppState.HOME
    state_history: List[str] = Field(default_factory=list)
    pending_confirmation: Optional[Dict[str, Any]] = None

    mode: Optional[LearningMode] = None
    topic: Optional[str] = None
    subtopic: Optional[str] = None
    difficulty: Optional[Difficulty] = None

    current_problem: Optional[Problem] = None
    current_attempt: int = 0
    reasoning_transcript: str = ""

    # input-understanding layer (surfaced on the dashboard for demo/debug)
    input_type: Optional[str] = None  # InputType value of the last turn
    extracted_answer: Optional[str] = None  # direct answer expression, if any
    step_walk: Optional[StepWalk] = None  # active guided step walk
    structured_reasoning: Optional[StructuredReasoning] = None
    verification_result: Optional[VerificationResult] = None
    misconception: Optional[Misconception] = None
    retrieved_memories: List[MemoryRecord] = Field(default_factory=list)
    stored_memories: List[MemoryRecord] = Field(default_factory=list)
    selected_intervention: Optional[Intervention] = None
    assistance_level: AssistanceLevel = AssistanceLevel.INDEPENDENT
    available_actions: List[str] = Field(default_factory=list)

    voice_status: VoiceStatus = VoiceStatus.IDLE
    voice_channel: str = ""  # "speech" | "text" | ""
    voice_provider: str = ""  # stt provider label
    paused: bool = False

    session_progress: SessionProgress = Field(default_factory=SessionProgress)
    turns: List[TurnRecord] = Field(default_factory=list)
    last_pipeline_events: List[PipelineEvent] = Field(default_factory=list)
    last_spoken: str = ""
    last_error: str = ""
    latency_ms: int = 0
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    version: int = 0
