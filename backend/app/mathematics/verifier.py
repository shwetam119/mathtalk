"""Deterministic mathematical verification with SymPy.

The LLM is never the final mathematical authority: every mathematical claim
from the reasoning interpreter is independently evaluated here with SymPy.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

import sympy as sp

from app.models.schemas import (
    ClaimStatus,
    MathClaim,
    Problem,
    StructuredReasoning,
    VerificationResult,
    Verdict,
)

# Canonical action labels produced by the reasoning interpreter.
# Critical labels mark operations that are mathematically invalid for the
# current problem type (used for plan validation and misconception evidence).
_CRITICAL_ACTIONS_BY_CONCEPT: Dict[str, List[str]] = {
    "linear_equation": [
        "added_constant_to_rhs",
        "added_constant_to_both_sides",
        "subtracted_constant_from_rhs_only",
        "divided_rhs_by_coefficient_only",
        "divided_by_constant",
        "divided_previous_result_by_coefficient",
        "multiplied_rhs_by_coefficient_only",
        "moved_constant_wrong_direction",
    ],
    "order_of_operations": ["evaluated_left_to_right"],
    "adding_fractions": [
        "added_numerators_only",
        "multiplied_numerators_and_denominators",
        "added_fractions_without_common_denominator",
    ],
    "combining_terms": ["combined_unlike_terms"],
    "distribution": ["distributed_incorrectly"],
    "probability": ["added_probabilities"],
    "equivalent_fractions": ["scaled_incorrectly"],
}

_VALID_ACTIONS: Dict[str, List[str]] = {
    "linear_equation": [
        "subtracted_constant_from_both_sides",
        "divided_both_sides_by_coefficient",
        "combined_like_terms",
        "distributed",
    ],
    "order_of_operations": ["evaluated_multiplication_first"],
    "adding_fractions": ["found_common_denominator", "added_numerators_with_common_denominator", "simplified_fraction"],
    "combining_terms": ["combined_like_terms"],
    "distribution": ["distributed"],
    "probability": ["used_favorable_over_total", "multiplied_probabilities"],
    "equivalent_fractions": ["scaled_numerator_and_denominator"],
}


def _concepts_of(problem: Problem) -> List[str]:
    return problem.concepts or []


def _relevant_concept(problem: Problem) -> str:
    for c in _concepts_of(problem):
        if c in _CRITICAL_ACTIONS_BY_CONCEPT:
            return c
    return problem.topic.lower().replace(" ", "_")


def _parse_eq(text: str) -> Optional[Tuple[str, str]]:
    """Split a claim text like '6 + 14 = 20' into (lhs, rhs)."""
    for sep in ["=", "equals"]:
        if sep in text:
            parts = text.split(sep, 1)
            return parts[0].strip(), parts[1].strip()
    return None


def _safe_sympify(expr: str):
    try:
        e = sp.sympify(expr)
        if e is None:
            return None
        return e
    except Exception:
        return None


def _normalize_multiplication(expr: str) -> str:
    """'2x' -> '2*x' so sympy can parse student-expressed coefficients."""
    return re.sub(r"(\d)x\b", r"\1*x", expr.replace("^", "**"))


def _split_equation(expr: str) -> Optional[Tuple[str, str]]:
    """Split '2x = 8' into (lhs, rhs); None when not an equation."""
    m = re.match(r"^\s*(.*?)\s*=\s*(.*?)\s*$", expr)
    return (m.group(1), m.group(2)) if m else None


def verify_step_expression(student_expr: str, expected_expr: str) -> bool:
    """Symbolic equivalence for a guided-step computation response.

    Handles plain expressions (2(x+2) == 2x+4), equivalent numbers (1/2 == 0.5)
    and derived equations ('2x = 8' == '2*x = 8'). Never a raw string compare.
    """
    try:
        a = _normalize_multiplication((student_expr or "").strip())
        b = _normalize_multiplication((expected_expr or "").strip())
        if not a or not b:
            return False
        ea = _split_equation(a)
        eb = _split_equation(b)
        if ea and eb:
            ok = True
            for sa_, sb_ in zip(ea, eb):
                la, lb = _safe_sympify(sa_), _safe_sympify(sb_)
                if la is None or lb is None or sp.simplify(la - lb) != 0:
                    ok = False
            return ok
        if ea or eb:
            return False  # one side is an equation, the other is not
        la, lb = _safe_sympify(a), _safe_sympify(b)
        if la is None or lb is None:
            return False
        return sp.simplify(la - lb) == 0
    except Exception:
        return False


def verify_direct_answer(
    problem: Problem,
    answer_expr: str,
    answer_variable: Optional[str] = None,
    raw_text: str = "",
    confidence: float = 0.95,
) -> VerificationResult:
    """Verify a short direct answer against the problem (SymPy authoritative)."""
    from app.models.schemas import DirectAnswer
    from app.reasoning.interpreter import ReasoningInterpreter

    answer = DirectAnswer(
        answer_expression=answer_expr,
        answer_variable=answer_variable,
        confidence=confidence,
        raw_text=raw_text or answer_expr,
    )
    structured = ReasoningInterpreter().from_direct_answer(problem, answer)
    return verify(structured, problem)


def _as_sympy_text(value) -> str:
    """Render a sympy value for display/compare purposes."""
    s = sp.nsimplify(value) if value.is_number else sp.simplify(value)
    return sp.sstr(s)


# One shared symbol so expressions parsed from different sources combine properly.
X = sp.Symbol("x")


def _parse_problem_equation(problem: Problem):
    """Parse '2x + 6 = 14' into (lhs_sympy, rhs_sympy, x)."""
    m = re.match(r"^\s*(.*?)\s*=\s*(.*?)\s*$", problem.display)
    if not m:
        return None
    lhs, rhs = m.group(1), m.group(2)
    try:
        l_src = re.sub(r"(\d)x\b", r"\1*x", lhs.replace("^", "**"))
        r_src = re.sub(r"(\d)x\b", r"\1*x", rhs.replace("^", "**"))
        l_e = sp.sympify(l_src, locals={"x": X})
        r_e = sp.sympify(r_src, locals={"x": X})
        return l_e, r_e, X
    except Exception:
        return None


def _solve_claim_check(claim: MathClaim, problem: Problem) -> Optional[MathClaim]:
    """Verify a 'x = v' claim by substituting into the problem equation."""
    eq = _parse_problem_equation(problem)
    if eq is None:
        return None
    lhs_e, rhs_e, x = eq
    v_src = claim.expected or claim.text.split("=")[-1].strip()
    try:
        v = sp.sympify(v_src, locals={"x": x})
    except Exception:
        return None
    diff = sp.simplify(lhs_e.subs(x, v) - rhs_e.subs(x, v))
    ok = diff == 0
    claim.status = ClaimStatus.VERIFIED if ok else ClaimStatus.CONTRADICTED
    claim.reason = (
        f"Substituting x = {v_src} into {problem.display} balances the equation."
        if ok
        else f"Substituting x = {v_src} does NOT balance {problem.display}."
    )
    claim.confidence = 1.0
    return claim


def _derived_equation_check(claim: MathClaim, problem: Problem) -> Optional[MathClaim]:
    """Verify an intermediate derived equation like '2x = 8' for ax + b = c."""
    src = f"{claim.expression or ''} = {claim.expected or ''}"
    m = re.match(r"^\s*(\d*)x\s*=\s*(-?\d+(?:/\d+)?)\s*$", src)
    if not m:
        return None
    eq = _parse_problem_equation(problem)
    if eq is None:
        return None
    coeff = int(m.group(1)) if m.group(1) else 1
    d = sp.sympify(m.group(2))
    lhs_e, rhs_e, x = eq
    # ax = d is a correct derived step iff ax == d implies the original equation
    # for the same x: i.e. rhs_e - b == d where b is the constant part of lhs.
    const = sp.simplify(lhs_e - coeff * x)
    if const.free_symbols:
        return None
    expected = sp.simplify(rhs_e - const)
    if sp.simplify(expected - d) == 0:
        claim.status = ClaimStatus.VERIFIED
        claim.reason = f"Correctly derived step: {m.group(0).replace(' ', '')}."
        claim.confidence = 1.0
    else:
        claim.status = ClaimStatus.CONTRADICTED
        claim.reason = f"The derived equation should be {coeff}x = {sp.sstr(expected)}, not {claim.expression} = {claim.expected}."
        claim.confidence = 1.0
    return claim


def verify_claim(claim: MathClaim, problem: Problem) -> MathClaim:
    """Evaluate one structured mathematical claim with SymPy."""
    lhs_src, rhs_src = claim.expression, claim.expected
    if not lhs_src:
        parsed = _parse_eq(claim.text)
        if parsed:
            lhs_src, rhs_src = parsed
    if not lhs_src:
        claim.status = ClaimStatus.UNSUPPORTED
        claim.reason = "No expression to verify."
        claim.confidence = 0.0
        return claim

    # normalize '2x' -> '2*x' so sympy can parse student expressions
    lhs_src = re.sub(r"(\d)x\b", r"\1*x", lhs_src)
    if rhs_src:
        rhs_src = re.sub(r"(\d)x\b", r"\1*x", rhs_src)

    # Derived intermediate equations: '2x = 8' inside a linear-equation solution.
    # (checked on the raw strings before sympy parsing)
    if lhs_src and rhs_src:
        derived = _derived_equation_check(claim, problem)
        if derived is not None:
            return derived

    lhs = _safe_sympify(lhs_src)
    rhs = _safe_sympify(rhs_src) if rhs_src else None

    if lhs is None:
        claim.status = ClaimStatus.UNSUPPORTED
        claim.reason = f"Could not parse expression: {lhs_src}"
        claim.confidence = 0.0
        return claim

    # Solving claims: 'x = v' verified by substitution into the equation.
    if claim.operation == "solve":
        checked = _solve_claim_check(claim, problem)
        if checked is not None:
            return checked
        target = _safe_sympify(problem.answer_expr)
        if target is not None:
            diff = sp.simplify(lhs - target)
            ok = diff == 0
            claim.status = ClaimStatus.VERIFIED if ok else ClaimStatus.CONTRADICTED
            claim.expected = problem.expected_answer
            claim.reason = "Matches the expected answer." if ok else (
                f"Expected {problem.expected_answer}, got {_as_sympy_text(lhs)}.")
            claim.confidence = 1.0
        return claim

    if rhs is None:
        # One-sided claim: compute it and compare with the problem's target if possible.
        computed = _as_sympy_text(lhs)
        claim.status = ClaimStatus.UNSUPPORTED
        claim.reason = f"Expression evaluates to {computed}."
        claim.confidence = 0.5
        return claim

    if rhs is None or _safe_sympify(rhs_src) is None:
        claim.status = ClaimStatus.UNSUPPORTED
        claim.reason = f"Could not parse the expected side: {rhs_src}"
        claim.confidence = 0.0
        return claim

    rhs_e = _safe_sympify(rhs_src)
    diff = sp.simplify(lhs - rhs_e)
    if diff == 0:
        claim.status = ClaimStatus.VERIFIED
        claim.reason = "Left and right sides are mathematically equal."
        claim.confidence = 1.0
        return claim

    # Symbolic claim that restates the problem itself ('2x + 6 = 14').
    if lhs.free_symbols and not diff.is_number:
        eq = _parse_problem_equation(problem)
        if eq is not None and rhs_e is not None:
            l_eq, r_eq, _ = eq
            if sp.simplify((lhs - rhs_e) - (l_eq - r_eq)) == 0:
                claim.status = ClaimStatus.VERIFIED
                claim.reason = "Restates the given equation."
                claim.confidence = 1.0
                return claim
        claim.status = ClaimStatus.UNCERTAIN
        claim.reason = f"Not an identity: the difference does not simplify to zero."
        claim.confidence = 0.3
        return claim

    claim.status = ClaimStatus.CONTRADICTED
    claim.expected = _as_sympy_text(rhs_e)
    claim.reason = f"Left side simplifies to {_as_sympy_text(lhs)}, not {_as_sympy_text(rhs_e)}."
    claim.confidence = 1.0
    return claim


def _check_action(action: str, problem: Problem) -> Tuple[bool, str]:
    """Is this canonical action valid for the problem type?"""
    concept = _relevant_concept(problem)
    critical = _CRITICAL_ACTIONS_BY_CONCEPT.get(concept, [])
    if action in critical:
        return False, f"'{action}' is not a valid move for this problem type."
    valid = _VALID_ACTIONS.get(concept, [])
    if action in valid:
        return True, "valid operation"
    # unknown actions: neutral (neither obviously valid nor invalid)
    return True, "neutral operation"


def _answer_matches(claim: MathClaim, problem: Problem) -> Optional[bool]:
    """Compare a claim's expression with the expected answer."""
    lhs = _safe_sympify(claim.expression or "")
    if lhs is None:
        return None
    expected = _safe_sympify(problem.answer_expr)
    if expected is None:
        return None
    return sp.simplify(lhs - expected) == 0


def verify(structured: StructuredReasoning, problem: Problem) -> VerificationResult:
    """Full deterministic verification of the student's reasoning."""
    result = VerificationResult(expected_answer=problem.expected_answer, correct_solution=problem.expected_answer)
    if problem.solution_steps:
        result.correct_solution = problem.solution_steps[-1]

    # 1. Verify every claim.
    for claim in structured.mathematical_claims:
        result.claims.append(verify_claim(claim, problem))

    # 2. Final answer check.
    student_answer = structured.final_answer
    result.student_answer = student_answer
    if student_answer:
        sa = _safe_sympify(_normalize_multiplication(student_answer))
        ea = _safe_sympify(_normalize_multiplication(problem.answer_expr))
        if sa is not None and ea is not None:
            result.final_answer_correct = sp.simplify(sa - ea) == 0
        elif student_answer.strip().lower() == problem.expected_answer.strip().lower():
            # unparseable-by-design answers (e.g. "true" / "false") compare textually
            result.final_answer_correct = True
        else:
            result.final_answer_correct = None
    elif result.claims:
        # infer the final answer from the last claim when it looks like a solve/evaluate
        last = result.claims[-1]
        if last.operation in ("solve", "evaluate") and last.expression:
            matched = _answer_matches(last, problem)
            if matched is not None:
                result.student_answer = last.expression
                result.final_answer_correct = matched

    # 3. Plan validation.
    critical_bad = []
    for action in structured.student_actions:
        ok, _ = _check_action(action, problem)
        concept = _relevant_concept(problem)
        if action in _CRITICAL_ACTIONS_BY_CONCEPT.get(concept, []):
            critical_bad.append(action)

    if result.final_answer_correct is False:
        result.plan_valid = False
    elif result.final_answer_correct is True:
        result.plan_valid = len(critical_bad) == 0
    else:
        result.plan_valid = None if not critical_bad else False

    # 4. Verdict.
    if result.final_answer_correct is True and result.plan_valid is True:
        result.verdict = Verdict.CORRECT
        result.reason = "Correct answer with sound reasoning."
    elif result.final_answer_correct is True and result.plan_valid is False:
        result.verdict = Verdict.INCORRECT
        result.reason = "Correct final answer but the reasoning/plan is flawed."
    elif result.final_answer_correct is False:
        result.verdict = Verdict.INCORRECT
        result.reason = "The final answer does not match the expected answer."
    elif structured.raw_transcript and not structured.mathematical_claims and not student_answer:
        result.verdict = Verdict.AMBIGUOUS
        result.reason = "No mathematical content could be extracted."
    else:
        result.verdict = Verdict.INCOMPLETE
        result.reason = "Reasoning is incomplete; no final answer was provided."

    return result
