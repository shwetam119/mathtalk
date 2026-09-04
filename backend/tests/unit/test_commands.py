"""Command-parser tests: global commands, numbered options, reasoning fallback."""
from __future__ import annotations

from app.models.schemas import AppState, IntentKind, SessionState
from app.state.commands import parse_intent


def _session(state: AppState = AppState.HOME, actions=None, pending=None):
    s = SessionState(app_state=state, available_actions=actions or [])
    if pending:
        s.pending_confirmation = pending
    return s


def test_help_variants():
    for t in ("help", "I need help", "help me", "what can I say"):
        assert parse_intent(t, _session()).kind == IntentKind.HELP


def test_repeat_variants():
    for t in ("repeat", "say that again", "repeat that", "again please"):
        assert parse_intent(t, _session()).kind == IntentKind.REPEAT


def test_go_back_variants():
    for t in ("go back", "back", "previous", "take me back"):
        assert parse_intent(t, _session()).kind == IntentKind.GO_BACK


def test_go_home_variants():
    for t in ("go home", "home", "main menu", "take me home"):
        assert parse_intent(t, _session()).kind == IntentKind.GO_HOME


def test_stop_and_resume():
    assert parse_intent("stop", _session()).kind == IntentKind.STOP
    assert parse_intent("pause", _session()).kind == IntentKind.STOP
    assert parse_intent("resume", _session()).kind == IntentKind.RESUME
    assert parse_intent("continue", _session()).kind == IntentKind.RESUME


def test_end_session_variants():
    for t in ("end session", "finish", "end the session", "i am done"):
        assert parse_intent(t, _session()).kind == IntentKind.END_SESSION


def test_numbered_options():
    actions = ["Learn", "Practice", "Test", "Review"]
    s = _session(AppState.HOME, actions=actions)
    for t, idx in [("1", 0), ("one", 0), ("option one", 0), ("first option", 0),
                   ("2", 1), ("two", 1), ("3", 2), ("option 4", 3), ("fourth", 3)]:
        p = parse_intent(t, s)
        assert p.kind == IntentKind.SELECT_OPTION, t
        assert p.option_index == idx, t
        assert p.option == actions[idx], t


def test_option_by_name():
    s = _session(AppState.HOME, actions=["Learn", "Practice", "Test", "Review"])
    p = parse_intent("practice", s)
    assert p.kind == IntentKind.SELECT_OPTION and p.option == "Practice"
    p = parse_intent("I want to practice", s)
    assert p.option == "Practice"


def test_subtopic_by_name():
    s = _session(AppState.SUBTOPIC_SELECTION, actions=["Linear Equations", "Simplifying Expressions"])
    p = parse_intent("linear equations", s)
    assert p.kind == IntentKind.SELECT_OPTION and p.option == "Linear Equations"


def test_open_reasoning_in_reasoning_state():
    s = _session(AppState.REASONING, actions=["Hint"])
    p = parse_intent("I add 6 and 14 to get 20 and then divide by 2", s)
    assert p.kind == IntentKind.SUBMIT_REASONING


def test_hint_in_reasoning_state():
    s = _session(AppState.REASONING, actions=["Hint"])
    for t in ("hint", "give me a hint", "I need a hint"):
        assert parse_intent(t, s).kind == IntentKind.REQUEST_HINT, t


def test_unknown_input_in_selection_state():
    s = _session(AppState.TOPIC_SELECTION, actions=["Arithmetic", "Algebra"])
    assert parse_intent("purple bananas", s).kind == IntentKind.UNKNOWN


def test_confirmation_yes_no():
    s = _session(AppState.MODE_SELECTION, pending={"type": "mode", "value": "practice"})
    assert parse_intent("yes", s).kind == IntentKind.CONFIRM_YES
    assert parse_intent("yeah that's right", s).kind == IntentKind.CONFIRM_YES
    assert parse_intent("no", s).kind == IntentKind.CONFIRM_NO


def test_empty_transcript_is_unknown():
    assert parse_intent("   ", _session()).kind == IntentKind.UNKNOWN


def test_numbers_do_not_leak_into_reasoning():
    # In REASONING state "1" is still a reasoning attempt? No: it resolves as reasoning
    s = _session(AppState.REASONING, actions=["Hint"])
    assert parse_intent("1", s).kind == IntentKind.SUBMIT_REASONING
