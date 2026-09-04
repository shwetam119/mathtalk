"""Self-correction detection/logging tests.

A genuine self-correction = the student's current attempt is verified CORRECT
while the session still carries the immediately-preceding non-correct attempt
for the same problem, which was diagnosed with a misconception. The engine
logs each such event as its own SELF_CORRECTION memory (with the corrected
misconception type) instead of merging it into the generic misconception
record.
"""
from __future__ import annotations

from app.models.schemas import AppState, MemoryType, Verdict

from tests.conftest import correct_for, drive_to_problem, flawed_for


def _self_corrections(memory, student_id="student-a"):
    return [
        m for m in memory.list_for_student(student_id)
        if m.memory_type == MemoryType.SELF_CORRECTION
    ]


def test_genuine_self_correction_is_detected_and_logged(engine, memory):
    """Wrong (misconception-diagnosed) attempt, then correct reasoning -> event."""
    session = drive_to_problem(engine)  # alg-le-01, 2x + 6 = 14
    assert session.current_problem.problem_id == "alg-le-01"

    r1 = engine.handle_turn(session, flawed_for(session.current_problem))
    engine.sessions.put(r1.session)
    session = r1.session
    assert session.app_state == AppState.INTERVENTION
    assert session.misconception.misconception_type == "inverse_operation"

    r2 = engine.handle_turn(session, correct_for(session.current_problem))
    assert r2.session.verification_result.verdict == Verdict.CORRECT
    assert r2.session.app_state == AppState.POST_RESPONSE_OPTIONS

    events = _self_corrections(memory)
    assert len(events) == 1, "exactly one self-correction event expected"
    ev = events[0]
    assert ev.memory_type.value == "self_correction"
    assert ev.metadata.get("misconception_type") == "inverse_operation"
    assert ev.concept == "linear_equation"
    assert ev.problem_id == "alg-le-01"
    assert "Self-corrected" in ev.description


def test_wrong_then_wrong_again_is_not_self_corrected(engine, memory):
    """A student who stays wrong is never marked self-corrected."""
    session = drive_to_problem(engine)
    r1 = engine.handle_turn(session, flawed_for(session.current_problem))
    engine.sessions.put(r1.session)
    session = r1.session
    assert session.verification_result.verdict == Verdict.INCORRECT

    # second attempt is ALSO wrong (the same misconception recurs)
    r2 = engine.handle_turn(session, flawed_for(session.current_problem))
    assert r2.session.verification_result.verdict == Verdict.INCORRECT
    assert r2.session.app_state == AppState.INTERVENTION

    assert _self_corrections(memory) == [], "wrong-then-wrong must not log a self-correction"
    # but the recurring misconception itself is still remembered
    miscon = [m for m in memory.list_for_student("student-a") if m.memory_type == MemoryType.MISCONCEPTION]
    assert miscon and miscon[0].metadata.get("frequency", 1) >= 2


def test_self_correction_requires_a_prior_wrong_attempt(engine, memory):
    """Solving correctly on the first try is NOT a self-correction."""
    session = drive_to_problem(engine)
    r = engine.handle_turn(session, correct_for(session.current_problem))
    assert r.session.verification_result.verdict == Verdict.CORRECT
    assert _self_corrections(memory) == []
