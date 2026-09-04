"""Fraction-addition demo path (end-to-end) tests.

The demo story: a student adds 1/3 + 1/4 by adding numerators AND
denominators. The full pipeline must flow  STT-stub (the transcript) ->
reasoning interpreter -> SymPy verifier -> _detect_fraction ->
fraction_denominator misconception -> memory store -> spoken intervention.

These tests pin that chain for the 1/3 + 1/4 problem (frac-add-03).
"""
from __future__ import annotations

from app.mathematics.problems import find_problem
from app.models.schemas import AppState, Difficulty, IntentKind, MemoryType, Verdict
from app.state.commands import ParsedIntent


def _drive_to_frac_add_03(engine, student_id: str = "student-a"):
    """Drive the voice flow to the 1/3 + 1/4 problem (frac-add-03).

    find_problem picks the lowest problem id, so the two earlier Adding
    Fractions problems are excluded to land on the demo problem directly.
    """
    session = engine.sessions.get_or_create(student_id)
    engine.start_session(session)
    for option in ("Practice", "Fractions", "Adding Fractions", "Easy"):
        parsed = ParsedIntent(IntentKind.SELECT_OPTION, option=option)
        session = engine.handle_intent(session, parsed).session
        engine.sessions.put(session)
    session.current_problem = find_problem(
        "Fractions", "Adding Fractions", Difficulty.EASY, exclude=["frac-add-01", "frac-add-02"]
    )
    session.app_state = AppState.REASONING
    engine.sessions.put(session)
    return engine.sessions.get(student_id)


def _misconception_memories(memory, student_id: str = "student-a"):
    return [m for m in memory.list_for_student(student_id) if m.memory_type == MemoryType.MISCONCEPTION]


def test_wrong_method_phrase_triggers_fraction_denominator(engine, memory):
    """The exact demo phrase flows to a targeted spoken intervention."""
    session = _drive_to_frac_add_03(engine)
    assert session.current_problem.problem_id == "frac-add-03"

    result = engine.handle_turn(
        session, "I add 1/3 and 1/4 by adding numerators and denominators"
    )
    s = result.session
    assert s.verification_result.verdict == Verdict.INCORRECT
    assert s.verification_result.final_answer_correct is False
    assert s.misconception.detected
    assert s.misconception.misconception_type == "fraction_denominator"
    assert s.misconception.confidence >= 0.7
    assert s.misconception.correct_answer_trap is False
    assert s.app_state == AppState.INTERVENTION

    # stored as its own misconception memory, retrievable like any other
    miscon = _misconception_memories(memory)
    assert len(miscon) == 1
    assert miscon[0].metadata.get("misconception_type") == "fraction_denominator"
    assert miscon[0].problem_id == "frac-add-03"

    # spoken intervention acknowledges the wrong method. First occurrence has
    # no matching learner memory yet, so the policy stays generic here (the
    # targeted, memory-based intervention only appears on a repeat occurrence).
    assert s.selected_intervention.type.value == "generic_intervention"
    assert s.selected_intervention.targeted is False
    assert "numerators" in result.spoken.lower()


def test_stated_wrong_result_is_not_praised(engine, memory):
    """A stated wrong result must never be verified as correct."""
    session = _drive_to_frac_add_03(engine)

    result = engine.handle_turn(session, "I add one third and one quarter to get two sevenths")
    s = result.session
    assert s.verification_result.student_answer == "2/7"
    assert s.verification_result.verdict == Verdict.INCORRECT
    assert s.misconception.detected
    assert s.misconception.misconception_type == "fraction_denominator"
    assert "numerators" in result.spoken.lower()


def test_correct_fraction_reasoning_is_verified(engine, memory):
    """Sound common-denominator reasoning is still praised, with no misconception."""
    session = _drive_to_frac_add_03(engine)

    result = engine.handle_turn(session, "I add one third and one quarter to get seven twelfths")
    s = result.session
    assert s.verification_result.verdict == Verdict.CORRECT
    assert s.misconception.detected is False
    assert s.app_state == AppState.POST_RESPONSE_OPTIONS
    assert _misconception_memories(memory) == []