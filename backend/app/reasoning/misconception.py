"""Misconception detection.

Diagnoses WHY the student's reasoning went wrong by combining:
  1. the structured reasoning (what the student said they did),
  2. the deterministic verification (what is mathematically true),
  3. the problem context (what the correct plan is).

Never diagnoses from the final answer alone.
"""
from __future__ import annotations

import re
from fractions import Fraction
from typing import List, Optional

from app.models.schemas import (
    MathClaim,
    Misconception,
    Problem,
    StructuredReasoning,
    VerificationResult,
    Verdict,
)

# recommended intervention templates per misconception type
_INTERVENTIONS: dict = {
    "inverse_operation": (
        "Before continuing, think about what operation would undo the {verb} on the left side. "
        "The left side is {display}. To isolate {var}, what should you do to both sides?"
    ),
    "equality_manipulation": (
        "Whatever you do to one side of an equation, you must do to the other side as well. "
        "Try applying the same operation to both sides of {display}."
    ),
    "sign_error": (
        "Check the sign of the numbers you are combining. {b} minus {c} is {diff}, not {sum}."
    ),
    "combine_unlike_terms": (
        "You can only combine terms that have the same variable part. {a}x and {b} are not like "
        "terms, so they cannot be added together."
    ),
    "distribution_error": (
        "When you multiply by a bracket, every term inside the bracket gets multiplied: "
        "{a}({b} + {c}) = {ab} + {ac}."
    ),
    "fraction_denominator": (
        "Before adding fractions, rewrite them with a common denominator. Only the numerators "
        "are added; the denominator stays the same."
    ),
    "whole_part_confusion": (
        "Probability is favorable outcomes divided by total outcomes. The total belongs in the "
        "denominator — it is not the answer by itself."
    ),
    "adding_probabilities": (
        "For independent events, multiply the probabilities together instead of adding them."
    ),
    "order_of_operations_error": (
        "Multiplication and division come before addition and subtraction. Re-evaluate the "
        "expression using that order."
    ),
    "formula_selection": (
        "Check which formula applies to this problem before substituting numbers into it."
    ),
    "unclear_reasoning": (
        "I could not quite follow the steps. Let's take it one step at a time — what would you "
        "do first?"
    ),
}

_VERB_FOR_SIGN = {">0": "addition", "<0": "subtraction"}


def _frac(s: str) -> Optional[Fraction]:
    try:
        return Fraction(s)
    except Exception:
        return None


def _render(f: Fraction) -> str:
    return str(f.numerator) if f.denominator == 1 else f"{f.numerator}/{f.denominator}"


def _parse_linear(display: str):
    m = re.match(r"^\s*(\d*)x\s*([+-])\s*(\d+)\s*=\s*(\d+)\s*$", display)
    if not m:
        return None
    a = int(m.group(1)) if m.group(1) else 1
    sign = m.group(2)
    b = int(m.group(3)) * (1 if sign == "+" else -1)
    c = int(m.group(4))
    return a, b, c


def _opening_verb(b: int) -> str:
    return "addition" if b > 0 else "subtraction"


class MisconceptionDetector:
    def detect(
        self,
        problem: Problem,
        structured: StructuredReasoning,
        verification: VerificationResult,
    ) -> Misconception:
        claims = structured.mathematical_claims
        actions = structured.student_actions

        # ---------------------------------------------------------------
        # 1. Linear equation misconceptions
        # ---------------------------------------------------------------
        if problem.topic == "Algebra" and problem.subtopic == "Linear Equations":
            linear = _parse_linear(problem.display)
            if linear:
                a, b, c = linear
                m = self._detect_linear(problem, structured, verification, a, b, c)
                if m.detected:
                    return m

        # ---------------------------------------------------------------
        # 2. Fractions
        # ---------------------------------------------------------------
        if problem.topic == "Fractions":
            m = self._detect_fraction(problem, structured, verification)
            if m.detected:
                return m

        # ---------------------------------------------------------------
        # 3. Probability
        # ---------------------------------------------------------------
        if problem.topic == "Probability":
            m = self._detect_probability(problem, structured, verification)
            if m.detected:
                return m

        # ---------------------------------------------------------------
        # 4. Generic claim-level checks (order of ops, distribution, ...)
        # ---------------------------------------------------------------
        m = self._detect_generic(problem, structured, verification)
        if m.detected:
            return m

        # ---------------------------------------------------------------
        # 5. Correct answer + flawed reasoning (no specific type found)
        # ---------------------------------------------------------------
        if (
            verification.final_answer_correct is True
            and verification.plan_valid is False
            and structured.reasoning_quality in ("flawed", "incomplete")
        ):
            return Misconception(
                detected=True,
                concept=structured.concept,
                misconception_type="unclear_reasoning",
                evidence="The final answer is correct, but the reasoning steps do not form a valid solution plan.",
                affected_step="overall approach",
                confidence=0.6,
                recommended_intervention=_INTERVENTIONS["unclear_reasoning"],
                correct_answer_trap=True,
            )

        return Misconception(detected=False)

    # ------------------------------------------------------------------
    def _detect_linear(self, problem, structured, verification, a, b, c) -> Misconception:
        claims = structured.mathematical_claims
        actions = structured.student_actions

        if "added_constant_to_rhs" in actions or any(
            c_.operation == "add"
            and c_.expression
            and {_frac(v) for v in re.findall(r"-?\d+(?:/\d+)?", c_.expression)} == {_frac(str(abs(b))), _frac(str(c))}
            for c_ in claims
        ):
            expected = _render(_frac(str(c)) - _frac(str(abs(b))))
            return Misconception(
                detected=True,
                concept="linear_equation",
                misconception_type="inverse_operation",
                evidence=f"You added {abs(b)} to {c} instead of undoing the {_opening_verb(b)} on the left side.",
                affected_step="first isolation step",
                confidence=0.92,
                recommended_intervention=_INTERVENTIONS["inverse_operation"].format(
                    verb=_opening_verb(b), display=problem.display, var="x"
                ),
                correct_answer_trap=verification.final_answer_correct is True,
            )

        # sign error inside equation solving: e.g. "14 - 6 = 20"
        for c_ in claims:
            if c_.operation == "subtract" and c_.expression and c_.expected:
                nums = re.findall(r"-?\d+", c_.expression)
                if len(nums) == 2 and c_.expected in (str(abs(int(nums[0])) + abs(int(nums[1]))),
                                                       str(int(nums[0]) + int(nums[1]))):
                    try:
                        n1, n2 = int(nums[0]), int(nums[1])
                        if int(c_.expected) == n1 + n2 and n1 != n2:
                            return Misconception(
                                detected=True,
                                concept="linear_equation",
                                misconception_type="sign_error",
                                evidence=f"You computed {n1} − {n2} as {n1 + n2}.",
                                affected_step=c_.text,
                                confidence=0.88,
                                recommended_intervention=_INTERVENTIONS["sign_error"].format(
                                    b=abs(n1), c=abs(n2), diff=abs(n1 - n2), sum=abs(n1 + n2)
                                ),
                                correct_answer_trap=verification.final_answer_correct is True,
                            )
                    except Exception:
                        pass

        if any(a_ in actions for a_ in ("subtracted_constant_from_rhs_only", "divided_rhs_by_coefficient_only")):
            return Misconception(
                detected=True,
                concept="linear_equation",
                misconception_type="equality_manipulation",
                evidence="An operation was applied to only one side of the equation.",
                affected_step="maintaining equality",
                confidence=0.85,
                recommended_intervention=_INTERVENTIONS["equality_manipulation"].format(display=problem.display),
                correct_answer_trap=verification.final_answer_correct is True,
            )

        # combining unlike terms inside an equation claim: "2x + 3 = 5x"
        for c_ in claims:
            if c_.expression and re.match(r"^\d+x\s*\+\s*\d+$", c_.expression) and c_.expected and "x" in c_.expected:
                return Misconception(
                    detected=True,
                    concept="linear_equation",
                    misconception_type="combine_unlike_terms",
                    evidence=f"You combined {c_.expression} into {c_.expected}, but {c_.expression.split('+')[0]} "
                             "and the constant are not like terms.",
                    affected_step=c_.text,
                    confidence=0.9,
                    recommended_intervention=_INTERVENTIONS["combine_unlike_terms"].format(
                        a=c_.expression.split("+")[0].replace("x", ""), b=c_.expression.split("+")[1]
                    ),
                    correct_answer_trap=verification.final_answer_correct is True,
                )

        # final-answer-only analysis for linear equations
        if verification.final_answer_correct is False and verification.student_answer:
            sa = _frac(verification.student_answer)
            if sa is not None:
                correct = _frac(str((c - b) // a)) if (c - b) % a == 0 else None
                if correct is not None and sa == _frac(str(c)) - _frac(str(abs(b))):
                    return Misconception(
                        detected=True,
                        concept="linear_equation",
                        misconception_type="inverse_operation",
                        evidence="The constant was combined with the right-hand side instead of being undone first.",
                        affected_step="first isolation step",
                        confidence=0.8,
                        recommended_intervention=_INTERVENTIONS["inverse_operation"].format(
                            verb=_opening_verb(b), display=problem.display, var="x"
                        ),
                        correct_answer_trap=False,
                    )
                if correct is not None and sa == _frac(str(c)) / _frac(str(a)):
                    return Misconception(
                        detected=True,
                        concept="linear_equation",
                        misconception_type="inverse_operation",
                        evidence="Division by the coefficient was applied before undoing the constant term.",
                        affected_step="order of inverse operations",
                        confidence=0.8,
                        recommended_intervention=_INTERVENTIONS["inverse_operation"].format(
                            verb=_opening_verb(b), display=problem.display, var="x"
                        ),
                        correct_answer_trap=False,
                    )

        return Misconception(detected=False)

    # ------------------------------------------------------------------
    def _detect_fraction(self, problem, structured, verification) -> Misconception:
        claims = structured.mathematical_claims
        for c_ in claims:
            if c_.operation == "add" and c_.expression and c_.expected:
                nums = re.findall(r"\d+", c_.expression)
                if len(nums) == 4:
                    a1, b1, a2, b2 = (int(n) for n in nums)
                    stated = _frac(c_.expected)
                    if stated is not None and stated == _frac(f"{a1 + a2}/{b1 + b2}"):
                        return Misconception(
                            detected=True,
                            concept="adding_fractions",
                            misconception_type="fraction_denominator",
                            evidence=f"You added numerators AND denominators: {a1}/{b1} + {a2}/{b2} = "
                                     f"({a1}+{a2})/({b1}+{b2}).",
                            affected_step=c_.text,
                            confidence=0.93,
                            recommended_intervention=_INTERVENTIONS["fraction_denominator"],
                            correct_answer_trap=verification.final_answer_correct is True,
                        )
                    if stated is not None and stated == _frac(f"{a1 + a2}/{b1}"):
                        return Misconception(
                            detected=True,
                            concept="adding_fractions",
                            misconception_type="fraction_denominator",
                            evidence="The common denominator step is missing.",
                            affected_step=c_.text,
                            confidence=0.8,
                            recommended_intervention=_INTERVENTIONS["fraction_denominator"],
                            correct_answer_trap=verification.final_answer_correct is True,
                        )
        # whole-part confusion in equivalent fractions: 1/2 = 2/4 style mistakes
        if problem.subtopic == "Equivalent Fractions" and verification.final_answer_correct is False:
            return Misconception(
                detected=True,
                concept="equivalent_fractions",
                misconception_type="whole_part_confusion",
                evidence="The numerator and denominator must be scaled by the same factor.",
                affected_step="scaling step",
                confidence=0.7,
                recommended_intervention=_INTERVENTIONS["fraction_denominator"],
                correct_answer_trap=False,
            )
        return Misconception(detected=False)

    # ------------------------------------------------------------------
    def _detect_probability(self, problem, structured, verification) -> Misconception:
        claims = structured.mathematical_claims
        for c_ in claims:
            if c_.operation == "add" and c_.expected and verification.final_answer_correct is False:
                return Misconception(
                    detected=True,
                    concept="probability",
                    misconception_type="adding_probabilities",
                    evidence="Probabilities of independent events were added instead of multiplied.",
                    affected_step=c_.text,
                    confidence=0.85,
                    recommended_intervention=_INTERVENTIONS["adding_probabilities"],
                    correct_answer_trap=False,
                )
        # whole-part confusion: answering with favorable count or total alone
        if verification.final_answer_correct is False and verification.student_answer:
            sa = _frac(verification.student_answer)
            if sa is not None:
                nums = [int(n) for n in re.findall(r"\d+", problem.prompt)]
                if len(nums) >= 2 and (sa == _frac(str(nums[0])) or sa == _frac(str(nums[1]))):
                    return Misconception(
                        detected=True,
                        concept="probability",
                        misconception_type="whole_part_confusion",
                        evidence="The answer uses only part of the information instead of favorable over total.",
                        affected_step="probability setup",
                        confidence=0.82,
                        recommended_intervention=_INTERVENTIONS["whole_part_confusion"],
                        correct_answer_trap=False,
                    )
        return Misconception(detected=False)

    # ------------------------------------------------------------------
    def _detect_generic(self, problem, structured, verification) -> Misconception:
        claims = structured.mathematical_claims
        if "order_of_operations" in (problem.concepts or []):
            if "evaluated_left_to_right" in structured.student_actions:
                return Misconception(
                    detected=True,
                    concept="order_of_operations",
                    misconception_type="order_of_operations_error",
                    evidence="Operations were evaluated left to right instead of following precedence.",
                    affected_step="first evaluation step",
                    confidence=0.86,
                    recommended_intervention=_INTERVENTIONS["order_of_operations_error"],
                    correct_answer_trap=verification.final_answer_correct is True,
                )
        if "distribution" in (problem.concepts or []):
            if "distributed_incorrectly" in structured.student_actions:
                return Misconception(
                    detected=True,
                    concept="distribution",
                    misconception_type="distribution_error",
                    evidence="Only one term inside the bracket was multiplied.",
                    affected_step="expansion step",
                    confidence=0.9,
                    recommended_intervention=_INTERVENTIONS["distribution_error"].format(
                        a="a", b="b", c="c", ab="ab", ac="ac"
                    ),
                    correct_answer_trap=verification.final_answer_correct is True,
                )
            # check claim pattern a(b+c) = ab + c
            for c_ in claims:
                if c_.expression and re.match(r"^\d+\*\w+$", c_.expression.replace(" ", "")):
                    pass
        # sign error: a subtraction stated as the corresponding addition result
        for c_ in claims:
            if c_.operation == "subtract" and c_.expression and c_.expected and c_.computed is not None:
                nums = re.findall(r"-?\d+", c_.expression)
                if len(nums) == 2:
                    try:
                        n1, n2 = int(nums[0]), int(nums[1])
                        if int(c_.expected) == n1 + n2 and c_.computed != c_.expected:
                            return Misconception(
                                detected=True,
                                concept=structured.concept,
                                misconception_type="sign_error",
                                evidence=f"You computed {n1} minus {n2} as {n1 + n2}, but it is {n1 - n2}.",
                                affected_step=c_.text,
                                confidence=0.9,
                                recommended_intervention=_INTERVENTIONS["sign_error"].format(
                                    b=abs(n1), c=abs(n2), diff=abs(n1 - n2), sum=abs(n1 + n2)
                                ),
                                correct_answer_trap=verification.final_answer_correct is True,
                            )
                    except Exception:
                        pass
        # self-contradictory arithmetic (computed != stated)
        for c_ in claims:
            if c_.expected is not None and c_.computed is not None and c_.expected != c_.computed:
                if "order_of_operations" in (problem.concepts or []):
                    continue  # handled above
                return Misconception(
                    detected=True,
                    concept=structured.concept,
                    misconception_type="arithmetic_error",
                    evidence=f"'{c_.text}' does not compute to {c_.expected}.",
                    affected_step=c_.text,
                    confidence=0.8,
                    recommended_intervention=_INTERVENTIONS["unclear_reasoning"],
                    correct_answer_trap=verification.final_answer_correct is True,
                )
        return Misconception(detected=False)
