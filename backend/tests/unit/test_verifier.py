"""Deterministic mathematical verification tests (SymPy)."""
from __future__ import annotations

import pytest

from app.mathematics.problems import find_problem
from app.mathematics.verifier import verify, verify_claim
from app.models.schemas import (
    ClaimStatus,
    Difficulty,
    MathClaim,
    StructuredReasoning,
    Verdict,
)

p_linear = find_problem("Algebra", "Linear Equations", Difficulty.EASY)  # 2x + 6 = 14
p_fraction = find_problem("Fractions", "Adding Fractions", Difficulty.EASY)
p_prob = find_problem("Probability", "Basic Probability", Difficulty.EASY)
p_oop = find_problem("Arithmetic", "Order of Operations", Difficulty.MEDIUM)


def test_arithmetic_claim_verified():
    claim = verify_claim(MathClaim(text="6 + 14 = 20", expression="6 + 14", expected="20"), p_linear)
    assert claim.status == ClaimStatus.VERIFIED


def test_arithmetic_claim_contradicted():
    claim = verify_claim(MathClaim(text="6 + 14 = 18", expression="6 + 14", expected="18"), p_linear)
    assert claim.status == ClaimStatus.CONTRADICTED


def test_solve_claim_by_substitution():
    claim = verify_claim(MathClaim(text="x = 4", expression="x", expected="4", operation="solve"), p_linear)
    assert claim.status == ClaimStatus.VERIFIED
    claim2 = verify_claim(MathClaim(text="x = 5", expression="x", expected="5", operation="solve"), p_linear)
    assert claim2.status == ClaimStatus.CONTRADICTED


def test_derived_equation_claim():
    claim = verify_claim(MathClaim(text="2x = 8", expression="2x", expected="8", operation="evaluate"), p_linear)
    assert claim.status == ClaimStatus.VERIFIED
    claim2 = verify_claim(MathClaim(text="2x = 9", expression="2x", expected="9", operation="evaluate"), p_linear)
    assert claim2.status == ClaimStatus.CONTRADICTED


def test_fraction_claims():
    ok = verify_claim(MathClaim(text="1/2 + 1/4 = 3/4", expression="1/2 + 1/4", expected="3/4"), p_fraction)
    assert ok.status == ClaimStatus.VERIFIED
    bad = verify_claim(MathClaim(text="1/2 + 1/4 = 2/6", expression="1/2 + 1/4", expected="2/6"), p_fraction)
    assert bad.status == ClaimStatus.CONTRADICTED


def test_probability_claim():
    c = verify_claim(MathClaim(text="3/8", expression="3/8", operation="evaluate"), p_prob)
    assert c.status in (ClaimStatus.UNSUPPORTED, ClaimStatus.VERIFIED)


def _verify(transcript: str, problem=p_linear):
    from app.reasoning.interpreter import ReasoningInterpreter

    sr = ReasoningInterpreter().interpret(problem, transcript)
    return sr, verify(sr, problem)


def test_verdict_correct():
    _, vr = _verify("I subtract 6 from both sides to get 2x equals 8, then divide both sides by 2 to get x equals 4.")
    assert vr.verdict == Verdict.CORRECT
    assert vr.final_answer_correct is True
    assert vr.plan_valid is True


def test_verdict_incorrect():
    _, vr = _verify("I add 6 and 14 to get 20 and then divide by 2.")
    assert vr.verdict == Verdict.INCORRECT
    assert vr.final_answer_correct is False


def test_correct_answer_trap():
    _, vr = _verify("I subtract 6 from 14 to get 8, then divide 8 by 2 to get 4.")
    assert vr.final_answer_correct is True
    assert vr.plan_valid is False
    assert vr.verdict == Verdict.INCORRECT


def test_incomplete_verdict():
    _, vr = _verify("I would subtract something")
    assert vr.verdict == Verdict.AMBIGUOUS


def test_verifier_ignores_llm():
    """Verification never depends on the interpreter source."""
    from app.reasoning.interpreter import ReasoningInterpreter

    sr = ReasoningInterpreter().interpret(p_linear, "x equals 4")
    sr.source = "llm+deterministic"  # pretend an LLM produced it
    vr = verify(sr, p_linear)
    assert vr.final_answer_correct is True


def test_restatement_claim_verified():
    c = verify_claim(MathClaim(text="2x + 6 = 14", expression="2x + 6", expected="14", operation="evaluate"), p_linear)
    assert c.status == ClaimStatus.VERIFIED
