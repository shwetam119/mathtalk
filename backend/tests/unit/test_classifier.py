"""Input-classifier tests: what the student meant, in context."""
from __future__ import annotations

from app.mathematics.problems import find_problem
from app.models.schemas import AppState, Difficulty, InputType, SessionState, StepWalk
from app.reasoning.classifier import InputClassifier


def _session(state=AppState.REASONING, step_walk=None, problem=None):
    s = SessionState(app_state=state)
    if step_walk:
        s.step_walk = step_walk
    return s


def _classify(text, state=AppState.REASONING, step_walk=None, problem=None):
    return InputClassifier().classify(text, _session(state, step_walk), problem)


def test_one_word_number_is_direct_answer():
    c = _classify("4")
    assert c.input_type == InputType.DIRECT_ANSWER
    assert c.direct_answer.answer_expression == "4"


def test_spoken_word_is_direct_answer():
    c = _classify("four")
    assert c.input_type == InputType.DIRECT_ANSWER
    assert c.direct_answer.answer_expression == "4"


def test_fraction_is_direct_answer():
    c = _classify("three quarters")
    assert c.input_type == InputType.DIRECT_ANSWER
    assert c.direct_answer.answer_expression == "3/4"


def test_variable_answer_is_direct_answer():
    c = _classify("x equals four")
    assert c.input_type == InputType.DIRECT_ANSWER
    assert c.direct_answer.answer_variable == "x"


def test_negative_is_direct_answer():
    c = _classify("negative five")
    assert c.input_type == InputType.DIRECT_ANSWER
    assert c.direct_answer.answer_expression == "-5"


def test_reasoning_sentence_is_reasoning():
    c = _classify("I add 6 and 14 to get 20 and then divide by 2")
    assert c.input_type == InputType.REASONING


def test_stuck_is_request_for_help():
    for t in ("I don't know", "I'm stuck", "I'm confused", "I can't do this"):
        c = _classify(t)
        assert c.input_type == InputType.REQUEST_FOR_HELP, t


def test_question_is_question():
    c = _classify("what is x?")
    assert c.input_type == InputType.QUESTION
    c = _classify("how do I solve this?")
    assert c.input_type == InputType.QUESTION


def test_yes_no():
    assert _classify("yes").input_type == InputType.CONFIRMATION
    assert _classify("no").input_type == InputType.REJECTION
    assert _classify("correct").input_type == InputType.CONFIRMATION


def test_step_walk_operation_response():
    problem = find_problem("Algebra", "Linear Equations", Difficulty.EASY)
    walk = StepWalk(problem_id=problem.problem_id, step_index=0, total_steps=4)
    c = _classify("subtract", step_walk=walk, problem=problem)
    assert c.input_type == InputType.DIRECT_ANSWER
    assert c.direct_answer.operation == "subtract"


def test_step_walk_expression_response():
    problem = find_problem("Algebra", "Linear Equations", Difficulty.EASY)
    walk = StepWalk(problem_id=problem.problem_id, step_index=1, total_steps=4)
    c = _classify("2x equals 8", step_walk=walk, problem=problem)
    assert c.input_type == InputType.DIRECT_ANSWER
    assert c.direct_answer.answer_expression == "2x = 8"


def test_step_walk_stuck_still_supportive():
    problem = find_problem("Algebra", "Linear Equations", Difficulty.EASY)
    walk = StepWalk(problem_id=problem.problem_id, step_index=0, total_steps=4)
    c = _classify("I don't know", step_walk=walk, problem=problem)
    assert c.input_type == InputType.REQUEST_FOR_HELP


def test_context_dependence_yes_no_not_answer():
    # "no" is a rejection, never a direct answer
    c = _classify("no")
    assert c.input_type == InputType.REJECTION
