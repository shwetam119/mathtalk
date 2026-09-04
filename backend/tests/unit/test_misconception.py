"""Misconception-detection tests: diagnosis from reasoning + verification + context."""
from __future__ import annotations

import pytest

from app.mathematics.problems import find_problem
from app.mathematics.verifier import verify
from app.models.schemas import Difficulty
from app.reasoning.interpreter import ReasoningInterpreter
from app.reasoning.misconception import MisconceptionDetector

detector = MisconceptionDetector()
interp = ReasoningInterpreter()

p_linear = find_problem("Algebra", "Linear Equations", Difficulty.EASY)
p_arith = find_problem("Arithmetic", "Addition and Subtraction", Difficulty.EASY)  # 47 + 38
p_frac = find_problem("Fractions", "Adding Fractions", Difficulty.EASY)  # 1/2 + 1/4
p_prob = find_problem("Probability", "Basic Probability", Difficulty.EASY)  # P(red) 3/8
p_comp = find_problem("Probability", "Compound Events", Difficulty.MEDIUM)  # P(HH)
p_oop = find_problem("Arithmetic", "Order of Operations", Difficulty.MEDIUM)


def _detect(problem, transcript):
    sr = interp.interpret(problem, transcript)
    vr = verify(sr, problem)
    return sr, vr, detector.detect(problem, sr, vr)


def test_inverse_operation():
    _, _, mc = _detect(p_linear, "I add 6 and 14 to get 20 and then divide by 2.")
    assert mc.detected
    assert mc.misconception_type == "inverse_operation"
    assert mc.confidence > 0.7
    assert "undo" in mc.recommended_intervention


def test_correct_answer_trap_detected():
    _, _, mc = _detect(p_linear, "I subtract 6 from 14 to get 8, then divide 8 by 2 to get 4.")
    assert mc.detected
    assert mc.misconception_type == "equality_manipulation"
    assert mc.correct_answer_trap is True


def test_no_misconception_on_sound_reasoning():
    _, _, mc = _detect(
        p_linear,
        "I subtract 6 from both sides to get 2x equals 8, then divide both sides by 2 to get x equals 4.",
    )
    assert not mc.detected


def test_sign_error():
    sr, vr, mc = _detect(p_linear, "I subtract 6 from 14 to get 20.")
    # 14 - 6 computed as 20 -> sign error
    assert mc.detected
    assert mc.misconception_type == "sign_error"


def test_combine_unlike_terms():
    _, _, mc = _detect(p_linear, "two x plus 6 equals 8x")
    assert mc.detected
    assert mc.misconception_type == "combine_unlike_terms"


def test_fraction_denominator():
    _, _, mc = _detect(p_frac, "one half plus one quarter equals two sixths")
    assert mc.detected
    assert mc.misconception_type == "fraction_denominator"


def test_whole_part_confusion():
    _, _, mc = _detect(p_prob, "the answer is 3")
    assert mc.detected
    assert mc.misconception_type == "whole_part_confusion"


def test_adding_probabilities():
    _, _, mc = _detect(p_comp, "one half plus one half equals one")
    assert mc.detected
    assert mc.misconception_type == "adding_probabilities"


def test_order_of_operations_error():
    _, _, mc = _detect(p_oop, "I add 2 and 3 to get 5, then multiply 5 by 4 to get 20.")
    assert mc.detected
    assert mc.misconception_type == "order_of_operations_error"


def test_diagnosis_not_from_final_answer_alone():
    """Same wrong final answer, different reasoning -> different diagnosis."""
    _, vr1, mc1 = _detect(p_linear, "I add 6 and 14 to get 20 and then divide by 2.")
    _, vr2, mc2 = _detect(p_linear, "two x plus 6 equals 8x")
    assert vr1.final_answer_correct is False
    assert vr2.final_answer_correct is not True  # no valid final answer either
    assert mc1.misconception_type == "inverse_operation"
    assert mc2.misconception_type == "combine_unlike_terms"
    assert mc1.misconception_type != mc2.misconception_type
