"""Session 1 -> Session 2 — the "Never Start From Zero" hero test.

Proves that learner memory stored in Session 1 changes tutoring behavior in
Session 2 (targeted vs generic intervention), through the real engine path.
"""
from __future__ import annotations

from app.models.schemas import AppState, IntentKind, MemoryType
from app.state.commands import ParsedIntent

from conftest import correct_for, drive_to_problem, flawed_for


def _select(engine, session, option):
    parsed = ParsedIntent(IntentKind.SELECT_OPTION, option=option)
    result = engine.handle_intent(session, parsed)
    engine.sessions.put(result.session)
    return result


def _run_session_1(engine, memory, student_id="student-a"):
    """Flawed reasoning -> hint -> correct reasoning -> end session."""
    session = drive_to_problem(engine, student_id)
    assert session.current_problem.problem_id == "alg-le-01"

    # 1. flawed reasoning
    r = engine.handle_turn(session, flawed_for(session.current_problem))
    engine.sessions.put(r.session)
    session = r.session
    assert session.app_state == AppState.INTERVENTION
    assert session.misconception.misconception_type == "inverse_operation"
    assert session.selected_intervention.memory_based is False  # no memory yet
    assert "Not quite" in r.spoken

    # 2. hint
    r = engine.handle_intent(session, ParsedIntent(IntentKind.REQUEST_HINT))
    engine.sessions.put(r.session)

    # 3. self-corrects
    session = engine.sessions.get(student_id)
    r = engine.handle_turn(session, correct_for(session.current_problem))
    engine.sessions.put(r.session)
    session = r.session
    assert session.app_state == AppState.POST_RESPONSE_OPTIONS
    assert session.session_progress.problems_correct == 1

    # memory: misconception memory stored and still active within this session
    mems = memory.list_for_student(student_id)
    miscon = [m for m in mems if m.memory_type == MemoryType.MISCONCEPTION]
    assert miscon, "misconception memory must be stored in Session 1"
    assert miscon[0].metadata.get("misconception_type") == "inverse_operation"

    # end session
    r = engine.handle_intent(session, ParsedIntent(IntentKind.END_SESSION))
    engine.sessions.put(r.session)
    return r.session


def _run_session_2(engine, memory, student_id="student-a"):
    """Related problem + flawed reasoning again -> memory must change behavior."""
    session = drive_to_problem(engine, student_id)  # new session for same student
    assert session.current_problem.problem_id != "alg-le-01"  # related problem
    assert session.session_number == 2

    r = engine.handle_turn(session, flawed_for(session.current_problem))
    engine.sessions.put(r.session)
    session = r.session
    assert session.app_state == AppState.INTERVENTION
    assert session.misconception.misconception_type == "inverse_operation"
    iv = session.selected_intervention
    assert iv.memory_based is True, "Session 2 must retrieve the Session 1 memory"
    assert iv.type.value == "targeted_intervention"
    assert "inverse" in iv.message
    assert "earlier" in iv.message.lower() or "before" in iv.message.lower()

    # the retrieved memory is visible to the dashboard
    assert any(
        m.metadata.get("misconception_type") == "inverse_operation"
        for m in session.retrieved_memories
    )

    # student self-corrects using the targeted guidance
    r = engine.handle_turn(session, correct_for(session.current_problem))
    engine.sessions.put(r.session)
    assert r.session.app_state == AppState.POST_RESPONSE_OPTIONS
    return r.session


def test_session1_to_session2_behavior_change(engine, memory):
    s1 = _run_session_1(engine, memory)
    s2 = _run_session_2(engine, memory)
    assert s1.session_number == 1
    assert s2.session_number == 2
    assert s1.student_id == s2.student_id


def test_without_memory_session1_is_generic(engine, memory):
    """Session 1 first-encounter intervention is NOT memory-based."""
    session = drive_to_problem(engine)
    r = engine.handle_turn(session, flawed_for(session.current_problem))
    assert r.session.selected_intervention.memory_based is False
    assert r.session.selected_intervention.type.value == "generic_intervention"


def test_session2_memory_demonstrated_through_api_path(engine, memory):
    """Same as hero test but driven via commands/transcripts like the UI does."""
    _run_session_1(engine, memory)
    s2 = drive_to_problem(engine)
    r = engine.handle_turn(s2, flawed_for(s2.current_problem))
    assert r.session.selected_intervention.memory_based is True
    # verify the stored memory actually exists in the memory store
    mems = memory.list_for_student("student-a")
    assert any(m.memory_type == MemoryType.MISCONCEPTION for m in mems)


def test_memory_resolved_after_cross_session_mastery(engine, memory):
    """When the learner masters the concept in Session 2, the old memory resolves."""
    _run_session_1(engine, memory)
    _run_session_2(engine, memory)
    mems = memory.list_for_student("student-a")
    miscon = [m for m in mems if m.memory_type == MemoryType.MISCONCEPTION]
    assert miscon
    # the Session-1 memory should now be resolved (mastery across sessions)
    assert all(m.status.value == "resolved" for m in miscon)
