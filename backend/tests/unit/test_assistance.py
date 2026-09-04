"""Progressive-assistance tests: levels, escalation, no early solutions."""
from __future__ import annotations

from app.mathematics.problems import find_problem
from app.models.schemas import AssistanceLevel, Difficulty
from app.tutoring.assistance import (
    detailed_solution,
    generic_hint,
    guided_explanation,
    level_label,
    review_approach,
)

p_linear = find_problem("Algebra", "Linear Equations", Difficulty.EASY)


def test_level_labels():
    assert level_label(AssistanceLevel.HINT) == "Hint"
    assert level_label(AssistanceLevel.DETAILED_SOLUTION) == "Detailed solution"


def test_generic_hint_never_reveals_answer():
    h = generic_hint(p_linear)
    assert "4" not in h
    assert "equation" in h or "side" in h


def test_guided_explanation_leaves_computation():
    g = guided_explanation(p_linear)
    assert "Step 1" in g or "step by step" in g
    assert p_linear.expected_answer not in g


def test_detailed_solution_reveals_steps_and_answer():
    d = detailed_solution(p_linear)
    assert p_linear.expected_answer in d
    assert "Step" in d or "1." in d or "2." in d


def test_review_approach_reflects_misconception():
    from app.reasoning.interpreter import ReasoningInterpreter
    from app.reasoning.misconception import MisconceptionDetector
    from app.mathematics.verifier import verify

    interp = ReasoningInterpreter()
    sr = interp.interpret(p_linear, "I add 6 and 14 to get 20 and then divide by 2.")
    vr = verify(sr, p_linear)
    mc = MisconceptionDetector().detect(p_linear, sr, vr)
    text = review_approach(p_linear, mc)
    assert "review" in text.lower() or "approach" in text.lower()
