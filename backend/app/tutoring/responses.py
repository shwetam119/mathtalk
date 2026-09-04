"""Natural-language response generation.

Every meaningful tutor turn ends with a small set of context-aware spoken
options — there are never dead-end states. The options come from the same
``available_actions`` list the state machine maintains.
"""
from __future__ import annotations

from typing import List, Optional

from app.models.schemas import (
    AssistanceLevel,
    Intervention,
    Misconception,
    Problem,
    SessionState,
    StructuredReasoning,
    VerificationResult,
    Verdict,
)

from .assistance import detailed_solution, generic_hint, guided_explanation, review_approach


def number_options(actions: List[str]) -> str:
    if not actions:
        return ""
    parts = [f"Option {i + 1}: {a}." for i, a in enumerate(actions)]
    return " ".join(parts)


class ResponseGenerator:
    # ------------------------------------------------------------------
    def welcome(self, session: SessionState) -> str:
        return (
            "Welcome to MathTalk, your voice-first mathematics tutor. "
            "What would you like to do? "
            + number_options(session.available_actions)
        )

    def confirm_mode(self, mode: str) -> str:
        return f"You selected {mode}. Is that correct? Say yes or no."

    def ask_topic(self, session: SessionState, topics: List[str]) -> str:
        return "Choose a topic. " + number_options(topics)

    def ask_subtopic(self, session: SessionState, subtopics: List[str]) -> str:
        return f"Choose a subtopic under {session.topic}. " + number_options(subtopics)

    def ask_difficulty(self, session: SessionState) -> str:
        return "Choose a difficulty. " + number_options(session.available_actions)

    def present_problem(self, session: SessionState, problem: Problem) -> str:
        q = problem.ask_question or ""
        lead = f" {q}" if q else ""
        return (
            f"Here is your problem.{lead} {problem.prompt} "
            "Tell me how you would solve it, in your own words."
        )

    def reasoning_prompt(self, session: SessionState, attempt: int) -> str:
        p = session.current_problem
        if not p:
            return "Tell me how you would solve it."
        if attempt > 1:
            return (
                f"Let's try again. Remember, the problem is: {p.prompt} "
                "Explain your approach step by step."
            )
        return f"Go ahead — how would you solve {p.prompt}?"

    # ------------------------------------------------------------------
    def diagnosis_response(
        self,
        problem: Problem,
        structured: StructuredReasoning,
        verification: VerificationResult,
        misconception: Misconception,
        intervention: Intervention,
    ) -> str:
        """The main tutor response after a reasoning turn (no dead ends)."""
        if verification.verdict == Verdict.CORRECT:
            return (
                intervention.message
                + " Would you like the next problem, to review your approach, or to end the session? "
                + number_options(intervention.next_actions)
            )

        if verification.final_answer_correct is True:
            # correct-answer trap
            parts = [
                "Interesting — your final answer is correct, but I want to check your method.",
            ]
            if misconception.detected and misconception.evidence:
                parts.append(f"I see that {misconception.evidence}")
            parts.append(intervention.message)
            parts.append("Would you like to try again, get a hint, or move to the next problem?")
            parts.append(number_options(intervention.next_actions))
            return " ".join(parts)

        parts = ["Not quite. Let's look at what you did."]
        if misconception.detected and misconception.evidence:
            ev = misconception.evidence.strip().rstrip(".")
            parts.append("I see that " + ev[0].lower() + ev[1:] + ".")
        if structured.final_answer:
            parts.append(f"Your final answer was {structured.final_answer}, but the correct answer is {verification.expected_answer}.")
        parts.append(intervention.message)
        parts.append("What would you like to do?")
        parts.append(number_options(intervention.next_actions))
        return " ".join(parts)

    # ------------------------------------------------------------------
    def incomplete_response(self, problem: Problem, structured: StructuredReasoning, intervention: Intervention) -> str:
        return (
            "I heard your thinking, but I need a bit more. What is your first step, "
            "and what do you get after that? "
            + number_options(intervention.next_actions)
        )

    def ambiguous_response(self, intervention: Intervention) -> str:
        return (
            "I'm sorry, I didn't catch any mathematics in that. "
            "Could you say your steps again, slowly? "
            + number_options(intervention.next_actions)
        )

    def hint_response(self, problem: Problem, level: AssistanceLevel, misconception: Misconception) -> str:
        if level == AssistanceLevel.HINT:
            if misconception and misconception.detected and misconception.recommended_intervention:
                msg = misconception.recommended_intervention
            else:
                msg = generic_hint(problem)
            return f"Here is a hint. {msg} Try again when you are ready."
        if level == AssistanceLevel.GUIDED_EXPLANATION:
            return "Let's work through it more closely. " + guided_explanation(problem) + " Try from here."
        if level == AssistanceLevel.DETAILED_SOLUTION:
            return detailed_solution(problem) + " Would you like the next problem?"
        return "Here is a hint. " + generic_hint(problem)

    def review_response(self, problem: Problem, misconception: Misconception) -> str:
        return review_approach(problem, misconception)

    # ------------------------------------------------------------------
    # direct answers / guided step walk (human-like, one step at a time)
    # ------------------------------------------------------------------
    _CORRECT_PRAISES = [
        "Correct! Well done.",
        "That's right!",
        "Exactly!",
        "Yes, that's correct.",
        "Nice work!",
    ]

    def direct_correct(self, problem: Problem) -> str:
        idx = sum(ord(c) for c in problem.problem_id) % len(self._CORRECT_PRAISES)
        return self._CORRECT_PRAISES[idx]

    def step_question(self, step, first: bool = False) -> str:
        q = step.question
        if first:
            q += " Say hint if you need help."
        return q

    def step_advance(self, step, next_step) -> str:
        return f"{step.confirm} {next_step.question}"

    def step_wrong_offer_hint(self, step) -> str:
        return f"Not quite. {step.hint} Would you like a hint? Say yes or no."

    def step_hint(self, step) -> str:
        return f"Sure. {step.hint} Try that now."

    def step_stuck(self, step) -> str:
        return f"That's okay. {step.hint} Try that now."

    def stuck_response(self, problem: Problem) -> str:
        from .assistance import generic_hint

        return f"That's okay. Let's take it one step at a time. {generic_hint(problem)}"

    def question_response(self, problem: Problem) -> str:
        return (
            f"Good question. The problem is: {problem.prompt} "
            "What would you do first?"
        )

    def ambiguous_number(self, candidate: str) -> str:
        return f"I'm not sure I caught that. Did you mean {candidate}?"

    def step_complete(self, step) -> str:
        return (
            f"{step.confirm} What would you like to do next? "
            + number_options(["Next problem", "Review", "End session"])
        )

    def solution_response(self, problem: Problem) -> str:
        return detailed_solution(problem) + " Would you like the next problem?"

    # ------------------------------------------------------------------
    def post_response_options(self, session: SessionState) -> str:
        p = session.current_problem
        base = "What would you like to do next? " + number_options(session.available_actions)
        if p:
            return f"You solved {p.prompt} correctly. {base}"
        return base

    def review_summary(self, session: SessionState) -> str:
        prog = session.session_progress
        lines = [
            "Here is your session summary.",
            f"You attempted {prog.problems_attempted} problems and solved {prog.problems_correct} correctly.",
            f"You used {prog.hints_used} hints across {prog.total_attempts} attempts.",
        ]
        if session.retrieved_memories:
            lines.append("I used your learning history to shape today's support.")
        lines.append("Would you like to practice more, or end the session?")
        lines.append(number_options(session.available_actions))
        return " ".join(lines)

    def end_summary(self, session: SessionState) -> str:
        prog = session.session_progress
        return (
            f"Great work today! You attempted {prog.problems_attempted} problems and solved "
            f"{prog.problems_correct} correctly. I have saved what we learned together, so next "
            "time we can pick up right where we left off. "
            "Say 'start a new session' to begin again, or 'home' to return to the main menu."
        )

    def help_text(self, session: SessionState) -> str:
        actions = session.available_actions or []
        base = (
            "Here is what you can say. Global commands: help, repeat, go back, go home, "
            "stop, resume, end session. "
        )
        if actions:
            base += "Right now you can say: " + number_options(actions)
        return base

    def recovery(self, message: str) -> str:
        return f"{message} Let's continue. " 

    def reprocess(self, session: SessionState) -> str:
        actions = session.available_actions or []
        return "I'm sorry, I didn't understand that. " + (
            "Please say one of the options: " + number_options(actions) if actions else "Could you repeat that?"
        )
