"""Contextual input understanding.

Sits between the deterministic command parser and the reasoning pipeline.
Decides WHAT the student meant (COMMAND / DIRECT_ANSWER / REASONING / QUESTION /
REQUEST_FOR_HELP / CONFIRMATION / REJECTION / UNCERTAIN / OTHER) using:

  * the current application state,
  * the active problem and its guided step (if a step walk is in progress),
  * the student utterance itself.

Deterministic rules run first (fast, predictable, keeps voice responsive).
When the deterministic decision is low-confidence, an optional LLM (Gemma)
is asked to classify; its JSON output is validated and never trusted blindly.
The classifier never changes state and never decides mathematical correctness.
"""
from __future__ import annotations

import re
from typing import Optional

from app.mathematics.spoken import (
    extract_direct_answer,
    match_operation,
    normalize_spoken_math,
)
from app.models.schemas import (
    DirectAnswer,
    InputClassification,
    InputType,
    Problem,
    SessionState,
)

# phrases that signal the student is stuck / frustrated / wants support
_STUCK = re.compile(
    r"\b(i don'?t know|i do not know|i'?m stuck|i am stuck|i'?m confused|i am confused|"
    r"i can'?t do this|i can not do this|i don'?t understand|i do not understand|"
    r"i give up|i'?m lost|i am lost|this is too hard|too hard|i can'?t figure)"
)
_YES = re.compile(r"^\s*(yes|yeah|yep|yup|sure|ok|okay|correct|that'?s right|thats right|affirmative|uh huh)\s*$")
_NO = re.compile(r"^\s*(no|nope|nah|not really|not that|wrong option)\s*$")
_QUESTION = re.compile(
    r"\b(what is|what's|what should|what do|how do|how should|why|which one|can you|"
    r"could you|is it|am i|does that|is that|what happens|what would)\b"
)
# words that are global commands / actions even mid-reasoning (defensive)
_COMMAND_WORDS = re.compile(
    r"\b(help|repeat|go back|go home|home|stop|pause|resume|continue|end session|"
    r"next problem|hint|show the solution|try again|review my approach)\b"
)


class InputClassifier:
    def __init__(self, llm=None):
        self.llm = llm  # optional LLMService (Gemma)

    # ------------------------------------------------------------------
    def classify(
        self,
        text: str,
        session: SessionState,
        problem: Optional[Problem] = None,
    ) -> InputClassification:
        t = (text or "").strip()
        if not t:
            return InputClassification(
                input_type=InputType.UNCERTAIN, confidence=0.0,
                source="deterministic", reason="empty input",
            )

        # 1. stuck / frustrated -> supportive step (never a dead end)
        if _STUCK.search(t.lower()):
            return InputClassification(
                input_type=InputType.REQUEST_FOR_HELP, confidence=0.98,
                source="deterministic", reason="student indicates uncertainty",
            )

        # 2. one-word yes / no
        low = t.lower().strip(" .,;:!?\t\n")
        if _YES.match(low):
            return InputClassification(
                input_type=InputType.CONFIRMATION, confidence=0.98,
                source="deterministic", reason="affirmative response",
            )
        if _NO.match(low):
            return InputClassification(
                input_type=InputType.REJECTION, confidence=0.98,
                source="deterministic", reason="negative response",
            )

        # 3. questions the student asks of the tutor
        if _QUESTION.search(low):
            return InputClassification(
                input_type=InputType.QUESTION, confidence=0.9,
                source="deterministic", reason="student asks a question",
            )

        # 4. guided step walk: a step response ("Subtract." / "2x equals 8")
        if session.step_walk and problem and problem.tutoring_steps:
            idx = session.step_walk.step_index
            if 0 <= idx < len(problem.tutoring_steps):
                step = problem.tutoring_steps[idx]
                if step.expected_op:
                    op = match_operation(t, [step.expected_op] + step.op_accept)
                    if op:
                        return InputClassification(
                            input_type=InputType.DIRECT_ANSWER,
                            direct_answer=DirectAnswer(
                                input_type=InputType.DIRECT_ANSWER,
                                answer_expression="",
                                operation=op,
                                confidence=0.97,
                                source="deterministic",
                                raw_text=t,
                            ),
                            confidence=0.97,
                            source="deterministic",
                            reason="guided step operation response",
                        )
                elif step.expected_expr:
                    norm = normalize_spoken_math(t)
                    if re.search(r"-?\d", norm):
                        da = DirectAnswer(
                            input_type=InputType.DIRECT_ANSWER,
                            answer_expression=norm,
                            confidence=0.96,
                            source="deterministic",
                            raw_text=t,
                        )
                    else:
                        da = extract_direct_answer(t)
                    if da:
                        return InputClassification(
                            input_type=InputType.DIRECT_ANSWER,
                            direct_answer=da,
                            confidence=0.96,
                            source="deterministic",
                            reason="guided step computation response",
                        )

        # 5. short direct answers ("4", "four", "x is 4", "the answer is five")
        da = extract_direct_answer(t)
        if da is not None:
            return InputClassification(
                input_type=InputType.DIRECT_ANSWER,
                direct_answer=da,
                confidence=da.confidence,
                source="deterministic",
                reason="short direct answer detected",
            )

        # 6. open-ended reasoning
        if _COMMAND_WORDS.search(low):
            return InputClassification(
                input_type=InputType.OTHER, confidence=0.5,
                source="deterministic", reason="possible command phrasing mid-reasoning",
            )
        return InputClassification(
            input_type=InputType.REASONING, confidence=0.7,
            source="deterministic", reason="open-ended speech treated as reasoning",
        )

    # ------------------------------------------------------------------
    def classify_with_llm(
        self,
        text: str,
        session: SessionState,
        problem: Optional[Problem] = None,
    ) -> InputClassification:
        """Deterministic classification first; ask Gemma only when uncertain."""
        det = self.classify(text, session, problem)
        if det.confidence >= 0.7 or not (self.llm and self.llm.is_configured):
            return det
        try:
            result = self.llm.classify_input(text, session, problem)
        except Exception:
            return det  # deterministic classification stands; never crash on LLM failure
        merged = self._merge(det, result)
        return merged or det

    # ------------------------------------------------------------------
    @staticmethod
    def _merge(det: InputClassification, llm_result: dict) -> Optional[InputClassification]:
        if not isinstance(llm_result, dict):
            return None
        raw_type = str(llm_result.get("input_type") or "").upper()
        try:
            input_type = InputType(raw_type)
        except ValueError:
            return None
        if input_type == InputType.DIRECT_ANSWER:
            expr = str(llm_result.get("answer_expression") or "").strip()
            if not expr:
                return None
            try:
                conf = float(llm_result.get("confidence") or 0.5)
            except (TypeError, ValueError):
                conf = 0.5
            return InputClassification(
                input_type=InputType.DIRECT_ANSWER,
                direct_answer=DirectAnswer(
                    input_type=InputType.DIRECT_ANSWER,
                    answer_expression=normalize_spoken_math(expr),
                    answer_variable=llm_result.get("answer_variable") or None,
                    confidence=min(conf, 0.98),
                    source="llm",
                    raw_text=str(llm_result.get("raw_text") or ""),
                ),
                confidence=min(conf, 0.98),
                source="llm",
                reason="llm classification",
            )
        return InputClassification(
            input_type=input_type,
            confidence=min(float(llm_result.get("confidence") or 0.6), 0.95),
            source="llm",
            reason="llm classification",
        )
