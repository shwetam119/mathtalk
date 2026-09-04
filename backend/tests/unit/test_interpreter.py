"""Reasoning-interpreter tests: transcript -> structured reasoning."""
from __future__ import annotations

import pytest

from app.mathematics.problems import find_problem
from app.models.schemas import Difficulty, StructuredReasoning
from app.reasoning.interpreter import ReasoningInterpreter, digitize

p_linear = find_problem("Algebra", "Linear Equations", Difficulty.EASY)  # 2x + 6 = 14
p_fraction = find_problem("Fractions", "Adding Fractions", Difficulty.EASY)  # 1/2 + 1/4
p_oop = find_problem("Arithmetic", "Order of Operations", Difficulty.MEDIUM)  # 2 + 3 x 4


@pytest.fixture(scope="module")
def interp():
    return ReasoningInterpreter()


def test_digitize_words(interp):
    assert digitize("two x plus six equals fourteen") == "2x plus 6 equals 14"
    assert digitize("one half plus one quarter") == "1/2 plus 1/4"
    assert digitize("three eighths") == "3/8"
    assert digitize("twenty-five") == "25"


def test_hero_flawed_case(interp):
    sr = interp.interpret(p_linear, "I add 6 and 14 to get 20 and then divide by 2.")
    assert isinstance(sr, StructuredReasoning)
    assert sr.final_answer == "10"
    assert sr.reasoning_quality == "sound"  # internally consistent, wrong plan
    assert "added_constant_to_rhs" in sr.student_actions
    texts = [c.text for c in sr.mathematical_claims]
    assert "6 + 14 = 20" in texts
    assert "20 / 2" in texts
    assert sr.confidence > 0.5


def test_correct_reasoning_case(interp):
    sr = interp.interpret(
        p_linear,
        "I subtract 6 from both sides to get 2x equals 8, then divide both sides by 2 to get x equals 4.",
    )
    assert sr.final_answer == "4"
    assert "subtracted_constant_from_both_sides" in sr.student_actions
    assert "divided_both_sides_by_coefficient" in sr.student_actions
    texts = [c.text for c in sr.mathematical_claims]
    assert "x = 4" in texts
    assert "2x = 8" in texts
    assert "8 / 2 = 4" in texts


def test_incomplete_reasoning(interp):
    sr = interp.interpret(p_linear, "I would subtract something")
    assert sr.final_answer is None
    assert sr.reasoning_quality in ("incomplete", "ambiguous")


def test_ambiguous_reasoning(interp):
    sr = interp.interpret(p_linear, "I don't know how to do this")
    assert sr.reasoning_quality == "ambiguous"
    assert not sr.mathematical_claims


def test_fraction_reasoning(interp):
    sr = interp.interpret(p_fraction, "one half plus one quarter equals three quarters")
    texts = [c.text for c in sr.mathematical_claims]
    assert "1/2 + 1/4 = 3/4" in texts


def test_multi_step_claims_in_order(interp):
    sr = interp.interpret(p_oop, "I add 2 and 3 to get 5, then multiply 5 by 4 to get 20.")
    ops = [c.operation for c in sr.mathematical_claims]
    assert ops[:2] == ["add", "multiply"]
    assert sr.final_answer == "20"


def test_raw_transcript_preserved(interp):
    t = "I add 6 and 14 to get 20."
    sr = interp.interpret(p_linear, t)
    assert sr.raw_transcript == t
