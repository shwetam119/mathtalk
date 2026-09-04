"""Integration tests across the pipeline stages."""
from __future__ import annotations

import pytest

from app.models.schemas import (
    AppState,
    IntentKind,
    MemoryType,
    VoiceStatus,
)
from app.services.rime import RimeUnavailable
from app.state.commands import ParsedIntent

from conftest import drive_to_problem


def _cmd(engine, session, intent: str, option=None):
    parsed = ParsedIntent(IntentKind[intent], option=option)
    result = engine.handle_intent(session, parsed)
    engine.sessions.put(result.session)
    return result


def test_speech_turn_drives_state(engine):
    from conftest import flawed_for

    session = drive_to_problem(engine)
    result = engine.handle_turn(session, flawed_for(session.current_problem), source="speech")
    assert result.session.app_state == AppState.INTERVENTION
    assert result.session.voice_channel == "speech"
    assert "Not quite" in result.spoken
    assert result.session.misconception.misconception_type == "inverse_operation"


def test_pipeline_events_present(engine):
    from conftest import flawed_for

    session = drive_to_problem(engine)
    result = engine.handle_turn(session, flawed_for(session.current_problem))
    stages = [e.stage for e in result.events]
    for expected in ("stt", "interpreter", "verifier", "misconception", "memory", "policy", "response"):
        assert expected in stages, stages


def test_voice_and_visual_share_state(engine):
    """Voice turn and visual command must mutate the same SessionState."""
    from conftest import flawed_for

    session = drive_to_problem(engine)
    r_voice = engine.handle_turn(session, flawed_for(session.current_problem), source="speech")
    engine.sessions.put(r_voice.session)
    saved = r_voice.session.model_dump()
    # the exact same object seen by the visual dashboard
    session2 = engine.sessions.get("student-a")
    assert session2.app_state == saved["app_state"]
    assert session2.reasoning_transcript == saved["reasoning_transcript"]


def test_empty_and_unknown_turns_do_not_crash(engine):
    session = drive_to_problem(engine)
    r1 = engine.handle_turn(session, "   ")
    assert r1.ok is False and "didn't hear" in r1.spoken.lower()
    engine.sessions.put(r1.session)
    session = engine.sessions.get("student-a")
    r2 = engine.handle_turn(session, "purple monkey dishwasher")
    # ambiguous reasoning in REASONING state -> the tutor re-prompts, no crash
    assert "didn't catch" in r2.spoken.lower()
    assert r2.session.app_state == AppState.REASONING


def test_hint_progresses_assistance(engine):
    from conftest import flawed_for

    session = drive_to_problem(engine)
    r0 = engine.handle_turn(session, flawed_for(session.current_problem))
    engine.sessions.put(r0.session)
    session = engine.sessions.get("student-a")
    r = _cmd(engine, session, "REQUEST_HINT")
    assert r.session.assistance_level.value >= 2  # hint level
    assert r.session.app_state == AppState.REASONING


def test_full_attempt_cycle(engine, memory):
    from conftest import correct_for, flawed_for

    session = drive_to_problem(engine)
    # flawed attempt
    r1 = engine.handle_turn(session, flawed_for(session.current_problem))
    engine.sessions.put(r1.session)
    # hint
    session = engine.sessions.get("student-a")
    r2 = _cmd(engine, session, "REQUEST_HINT")
    # retry correctly
    r3 = engine.handle_turn(r2.session, correct_for(r2.session.current_problem))
    assert r3.session.app_state == AppState.POST_RESPONSE_OPTIONS
    prog = r3.session.session_progress
    assert prog.total_attempts == 2
    assert prog.problems_correct == 1
    assert prog.hints_used == 1
    # memories were stored: misconception + attempts + strength
    all_mem = memory.list_for_student("student-a")
    types = {m.memory_type.value for m in all_mem}
    assert "misconception" in types
    assert "attempt" in types
    assert "strength" in types


def test_stop_resume_pause(engine):
    session = drive_to_problem(engine)
    r = _cmd(engine, session, "STOP")
    assert r.session.paused is True
    r2 = _cmd(engine, r.session, "RESUME")
    assert r2.session.paused is False


def test_go_home_resets_navigation(engine):
    session = drive_to_problem(engine)
    r = _cmd(engine, session, "GO_HOME")
    assert r.session.app_state == AppState.HOME
    assert r.session.mode is None and r.session.current_problem is None


def test_go_back_retraces_steps(engine):
    """GO_BACK must step back one user-facing state, not always collapse to HOME."""
    session = engine.sessions.get_or_create("back-student")
    engine.start_session(session)
    r = _cmd(engine, session, "SELECT_OPTION", option="Practice")
    assert r.session.app_state == AppState.TOPIC_SELECTION
    r = _cmd(engine, r.session, "SELECT_OPTION", option="Algebra")
    assert r.session.app_state == AppState.SUBTOPIC_SELECTION
    r = _cmd(engine, r.session, "GO_BACK")
    assert r.session.app_state == AppState.TOPIC_SELECTION
    r = _cmd(engine, r.session, "GO_BACK")
    assert r.session.app_state == AppState.HOME


def test_mode_confirmation_declares_state(conf):
    """When confirmation is on, the machine declares MODE_SELECTION while
    awaiting the yes/no, and yes/no transition exactly like the spec."""
    from app.main import build_engine

    conf2 = conf.model_copy(update={"confirm_mode_selection": True})
    eng = build_engine(conf2)["engine"]
    session = eng.sessions.get_or_create("conf-student")
    eng.start_session(session)

    r = _cmd(eng, session, "SELECT_OPTION", option="Practice")
    assert r.session.app_state == AppState.MODE_SELECTION
    assert r.session.pending_confirmation is not None
    assert "Is that correct" in r.spoken
    assert r.session.available_actions == ["Learn", "Practice", "Test", "Review"]

    r2 = _cmd(eng, r.session, "CONFIRM_YES")
    assert r2.session.app_state == AppState.TOPIC_SELECTION
    assert r2.session.pending_confirmation is None


def test_mode_confirmation_no_returns_to_selection(conf):
    from app.main import build_engine

    conf2 = conf.model_copy(update={"confirm_mode_selection": True})
    eng = build_engine(conf2)["engine"]
    session = eng.sessions.get_or_create("conf-no-student")
    eng.start_session(session)
    r = _cmd(eng, session, "SELECT_OPTION", option="Practice")
    r = _cmd(eng, r.session, "CONFIRM_NO")
    assert r.session.app_state == AppState.MODE_SELECTION
    assert r.session.pending_confirmation is None
    assert "Welcome to MathTalk" in r.spoken


def test_go_back_clears_pending_confirmation(conf):
    from app.main import build_engine

    conf2 = conf.model_copy(update={"confirm_mode_selection": True})
    eng = build_engine(conf2)["engine"]
    session = eng.sessions.get_or_create("conf-back-student")
    eng.start_session(session)
    r = _cmd(eng, session, "SELECT_OPTION", option="Practice")
    assert r.session.pending_confirmation is not None
    r = _cmd(eng, r.session, "GO_BACK")
    assert r.session.app_state == AppState.HOME
    assert r.session.pending_confirmation is None


def test_rime_lifecycle_without_credentials(services):
    """Without credentials, Rime reports the exact missing config and raises."""
    rime = services["rime"]
    status = rime.status()
    assert status["configured"] is False
    assert "RIME_API_KEY" in status["missing"]
    with pytest.raises(RimeUnavailable):
        rime.synthesize("hello")


def test_rime_reports_configuration_requirements(services):
    status = services["rime"].status()
    assert "RIME_API_KEY" in status["missing"]
    assert "rime" in status["note"].lower()


def test_memory_retrieval_feeds_policy(engine, memory):
    """Pre-seeded Qdrant/local memory changes the intervention in a real turn."""
    from conftest import flawed_for

    session = drive_to_problem(engine)
    # simulate a previous session's memory
    memory.store_memory(
        student_id="student-a",
        session_id="old-session",
        source_session="session-1",
        concept="linear_equation",
        topic="Algebra",
        subtopic="Linear Equations",
        memory_type=MemoryType.MISCONCEPTION,
        description="inverse operation guidance",
        evidence="added the constant instead of subtracting",
        confidence=0.92,
        metadata={"misconception_type": "inverse_operation", "frequency": 2},
    )
    result = engine.handle_turn(session, flawed_for(session.current_problem))
    iv = result.session.selected_intervention
    assert iv.memory_based is True
    assert iv.type.value == "targeted_intervention"
    assert "inverse" in iv.message
    # the retrieved memory is visible on the state for the dashboard
    assert any(m.metadata.get("misconception_type") == "inverse_operation"
               for m in result.session.retrieved_memories)
