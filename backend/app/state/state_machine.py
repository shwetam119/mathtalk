"""The single authoritative state machine for MathTalk.

Every state transition in the application goes through this module. Both the
voice interface and the visual dashboard read and modify the same
``SessionState``; there is no duplicated state logic anywhere else.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from app.models.schemas import AppState, IntentKind, SessionState

# Transient states the pipeline passes through; they are never presented to
# the user as a place to make a choice.
_TRANSIENT = {
    AppState.PROBLEM_PRESENTATION,
    AppState.DIAGNOSIS,
    AppState.NEXT_PROBLEM,
    AppState.ERROR_RECOVERY,
}

# Global intents that are valid in every user-facing state.
GLOBAL_INTENTS = {
    IntentKind.HELP,
    IntentKind.REPEAT,
    IntentKind.GO_BACK,
    IntentKind.GO_HOME,
    IntentKind.STOP,
    IntentKind.RESUME,
    IntentKind.END_SESSION,
}

_SELECTION_STATES = {
    AppState.HOME,
    AppState.MODE_SELECTION,
    AppState.TOPIC_SELECTION,
    AppState.SUBTOPIC_SELECTION,
    AppState.DIFFICULTY_SELECTION,
}

# Default contextual actions per user-facing state. Topic/subtopic lists are
# filled in from the problem catalog by the orchestrator.
_DEFAULT_ACTIONS: Dict[AppState, List[str]] = {
    AppState.HOME: ["Learn", "Practice", "Test", "Review"],
    AppState.MODE_SELECTION: ["Learn", "Practice", "Test", "Review"],
    AppState.DIFFICULTY_SELECTION: ["Easy", "Medium", "Hard"],
    AppState.PROBLEM_PRESENTATION: ["Repeat the problem"],
    AppState.REASONING: ["Hint"],
    AppState.INTERVENTION: ["Try again", "Hint", "Review my approach", "Show the solution"],
    AppState.POST_RESPONSE_OPTIONS: ["Next problem", "Review", "End session"],
    AppState.REVIEW: ["Practice more", "End session"],
    AppState.END_SESSION: ["Start a new session"],
    AppState.ERROR_RECOVERY: ["Repeat", "Go back", "Help"],
}

# (from_state, intent) -> to_state  for the deterministic core flow.
_TRANSITIONS: Dict[Tuple, AppState] = {
    # --- entry -----------------------------------------------------------
    (AppState.HOME, IntentKind.SELECT_OPTION): AppState.MODE_SELECTION,
    (AppState.MODE_SELECTION, IntentKind.CONFIRM_YES): AppState.TOPIC_SELECTION,
    (AppState.MODE_SELECTION, IntentKind.CONFIRM_NO): AppState.MODE_SELECTION,
    (AppState.MODE_SELECTION, IntentKind.SELECT_OPTION): AppState.MODE_SELECTION,
    # --- topic / subtopic / difficulty -----------------------------------
    (AppState.TOPIC_SELECTION, IntentKind.SELECT_OPTION): AppState.SUBTOPIC_SELECTION,
    (AppState.SUBTOPIC_SELECTION, IntentKind.SELECT_OPTION): AppState.DIFFICULTY_SELECTION,
    (AppState.DIFFICULTY_SELECTION, IntentKind.SELECT_OPTION): AppState.PROBLEM_PRESENTATION,
    (AppState.PROBLEM_PRESENTATION, IntentKind.SELECT_OPTION): AppState.REASONING,
    # --- reasoning -> diagnosis -> intervention ---------------------------
    (AppState.REASONING, IntentKind.SUBMIT_REASONING): AppState.DIAGNOSIS,
    (AppState.REASONING, IntentKind.REQUEST_HINT): AppState.REASONING,
    (AppState.DIAGNOSIS, IntentKind.SELECT_OPTION): AppState.INTERVENTION,
    (AppState.DIAGNOSIS, IntentKind.NEXT_PROBLEM): AppState.POST_RESPONSE_OPTIONS,
    # --- intervention -----------------------------------------------------
    (AppState.INTERVENTION, IntentKind.TRY_AGAIN): AppState.REASONING,
    (AppState.INTERVENTION, IntentKind.REQUEST_HINT): AppState.REASONING,
    (AppState.INTERVENTION, IntentKind.REVIEW_APPROACH): AppState.REASONING,
    (AppState.INTERVENTION, IntentKind.SHOW_SOLUTION): AppState.POST_RESPONSE_OPTIONS,
    (AppState.INTERVENTION, IntentKind.NEXT_PROBLEM): AppState.NEXT_PROBLEM,
    # --- post response -----------------------------------------------------
    (AppState.POST_RESPONSE_OPTIONS, IntentKind.NEXT_PROBLEM): AppState.NEXT_PROBLEM,
    (AppState.POST_RESPONSE_OPTIONS, IntentKind.SELECT_OPTION): AppState.TOPIC_SELECTION,
    (AppState.POST_RESPONSE_OPTIONS, IntentKind.PRACTICE_MORE): AppState.TOPIC_SELECTION,
    (AppState.POST_RESPONSE_OPTIONS, IntentKind.END_SESSION): AppState.END_SESSION,
    (AppState.POST_RESPONSE_OPTIONS, IntentKind.TRY_AGAIN): AppState.REASONING,
    # --- next problem ------------------------------------------------------
    (AppState.NEXT_PROBLEM, IntentKind.SELECT_OPTION): AppState.PROBLEM_PRESENTATION,
    # --- review -------------------------------------------------------------
    (AppState.REVIEW, IntentKind.PRACTICE_MORE): AppState.TOPIC_SELECTION,
    (AppState.REVIEW, IntentKind.SELECT_OPTION): AppState.TOPIC_SELECTION,
    (AppState.REVIEW, IntentKind.END_SESSION): AppState.END_SESSION,
    # --- end ----------------------------------------------------------------
    (AppState.END_SESSION, IntentKind.START_NEW_SESSION): AppState.HOME,
    (AppState.END_SESSION, IntentKind.SELECT_OPTION): AppState.HOME,
    # --- recovery ------------------------------------------------------------
    (AppState.ERROR_RECOVERY, IntentKind.GO_BACK): AppState.ERROR_RECOVERY,  # resolved by orchestrator
    (AppState.ERROR_RECOVERY, IntentKind.REPEAT): AppState.ERROR_RECOVERY,
    (AppState.ERROR_RECOVERY, IntentKind.HELP): AppState.ERROR_RECOVERY,
}


def is_user_facing(state: AppState) -> bool:
    return state not in _TRANSIENT


def next_state(current: AppState, intent: IntentKind) -> AppState:
    """Deterministic state transition for the core flow.

    Raises ``InvalidTransition`` when the intent is not applicable in the
    current state; callers must handle that by re-prompting.
    """
    if intent in GLOBAL_INTENTS:
        if intent == IntentKind.GO_HOME:
            return AppState.HOME
        if intent == IntentKind.END_SESSION:
            return AppState.END_SESSION
        # help/repeat/stop/resume/go_back keep the app state.
        return current
    key = (current, intent)
    if key in _TRANSITIONS:
        return _TRANSITIONS[key]
    # Selection states accept option selection generically.
    if intent == IntentKind.SELECT_OPTION and current in _SELECTION_STATES:
        if current == AppState.HOME:
            return AppState.MODE_SELECTION
        if current == AppState.MODE_SELECTION:
            return AppState.MODE_SELECTION
        return _TRANSITIONS.get(key, current)
    raise InvalidTransition(f"{intent.value} is not valid in {current.value}")


def compute_available_actions(session: SessionState) -> List[str]:
    """Contextual spoken/visual actions for the current state."""
    actions: List[str] = list(_DEFAULT_ACTIONS.get(session.app_state, []))
    if session.app_state in (AppState.TOPIC_SELECTION, AppState.SUBTOPIC_SELECTION):
        # Filled in by the orchestrator with catalog data.
        pass
    if session.app_state == AppState.REASONING and session.current_problem:
        actions = ["Hint"]
    return actions


def push_history(session: SessionState) -> None:
    prev = session.app_state.value
    if not session.state_history or session.state_history[-1] != prev:
        session.state_history.append(prev)
        if len(session.state_history) > 12:
            session.state_history = session.state_history[-12:]


def go_back(session: SessionState) -> AppState:
    """Return to the previous logical state (deterministic, history-based)."""
    while session.state_history:
        prev = session.state_history.pop()
        try:
            candidate = AppState(prev)
        except ValueError:
            continue
        if candidate != session.app_state and is_user_facing(candidate):
            return candidate
    return AppState.HOME


def bump(session: SessionState) -> None:
    import time

    session.updated_at = time.time()
    session.version += 1


class InvalidTransition(Exception):
    pass
