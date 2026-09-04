"""State-machine transition tests."""
from __future__ import annotations

import pytest

from app.models.schemas import AppState, IntentKind, SessionState
from app.state.state_machine import (
    InvalidTransition,
    compute_available_actions,
    go_back,
    next_state,
    push_history,
)


def test_core_flow_transitions():
    flow = [
        (AppState.HOME, IntentKind.SELECT_OPTION, AppState.MODE_SELECTION),
        (AppState.MODE_SELECTION, IntentKind.CONFIRM_YES, AppState.TOPIC_SELECTION),
        (AppState.TOPIC_SELECTION, IntentKind.SELECT_OPTION, AppState.SUBTOPIC_SELECTION),
        (AppState.SUBTOPIC_SELECTION, IntentKind.SELECT_OPTION, AppState.DIFFICULTY_SELECTION),
        (AppState.DIFFICULTY_SELECTION, IntentKind.SELECT_OPTION, AppState.PROBLEM_PRESENTATION),
        (AppState.REASONING, IntentKind.SUBMIT_REASONING, AppState.DIAGNOSIS),
        (AppState.DIAGNOSIS, IntentKind.SELECT_OPTION, AppState.INTERVENTION),
        (AppState.INTERVENTION, IntentKind.TRY_AGAIN, AppState.REASONING),
        (AppState.INTERVENTION, IntentKind.REQUEST_HINT, AppState.REASONING),
        (AppState.INTERVENTION, IntentKind.SHOW_SOLUTION, AppState.POST_RESPONSE_OPTIONS),
        (AppState.POST_RESPONSE_OPTIONS, IntentKind.NEXT_PROBLEM, AppState.NEXT_PROBLEM),
        (AppState.POST_RESPONSE_OPTIONS, IntentKind.END_SESSION, AppState.END_SESSION),
        (AppState.END_SESSION, IntentKind.START_NEW_SESSION, AppState.HOME),
    ]
    for src, intent, dst in flow:
        assert next_state(src, intent) == dst, f"{src} + {intent} -> {dst}"


def test_global_intents_keep_state():
    for state in AppState:
        for intent in (IntentKind.HELP, IntentKind.REPEAT, IntentKind.GO_BACK,
                       IntentKind.STOP, IntentKind.RESUME):
            assert next_state(state, intent) == state


def test_go_home_and_end_session_are_global():
    assert next_state(AppState.REASONING, IntentKind.GO_HOME) == AppState.HOME
    assert next_state(AppState.REASONING, IntentKind.END_SESSION) == AppState.END_SESSION


def test_invalid_transition_raises():
    with pytest.raises(InvalidTransition):
        next_state(AppState.REASONING, IntentKind.SHOW_SOLUTION)


def test_go_back_pops_history():
    s = SessionState()
    push_history(s)
    s.app_state = AppState.MODE_SELECTION
    push_history(s)
    s.app_state = AppState.TOPIC_SELECTION
    assert go_back(s) == AppState.MODE_SELECTION
    assert go_back(s) == AppState.HOME  # empty history -> HOME


def test_go_back_skips_transient_states():
    s = SessionState()
    s.app_state = AppState.PROBLEM_PRESENTATION
    push_history(s)
    s.app_state = AppState.REASONING
    push_history(s)
    # PROBLEM_PRESENTATION is transient, so go_back lands further back
    assert go_back(s) != AppState.PROBLEM_PRESENTATION


def test_available_actions_present_in_all_states():
    s = SessionState()
    for state in AppState:
        s.app_state = state
        actions = compute_available_actions(s)
        assert isinstance(actions, list)


def test_no_duplicate_history_entries():
    s = SessionState()
    push_history(s)
    push_history(s)
    assert len(s.state_history) == 1
