"""Guided step-walk tests: smallest-useful-intervention after a wrong answer."""
from __future__ import annotations

from app.models.schemas import AppState, IntentKind, LearningMode, Verdict
from app.state.commands import ParsedIntent
from tests.conftest import drive_to_problem


def _turn(engine, session, text):
    r = engine.handle_turn(session, text, source="text")
    engine.sessions.put(r.session)
    return r


def _cmd(engine, session, kind):
    r = engine.handle_intent(session, ParsedIntent(kind))
    engine.sessions.put(r.session)
    return r


def test_full_step_walk_demo(engine):
    session = drive_to_problem(engine)  # 2x + 6 = 14
    r = _turn(engine, session, "5")
    assert r.session.step_walk is not None and r.session.step_walk.step_index == 0
    assert "do with the 6" in r.spoken

    r = _turn(engine, r.session, "Subtract.")
    assert r.session.step_walk.step_index == 1
    assert "does that leave" in r.spoken

    r = _turn(engine, r.session, "2x equals 8")
    assert r.session.step_walk.step_index == 2
    assert "do with the 2" in r.spoken

    r = _turn(engine, r.session, "divide by 2")
    assert r.session.step_walk.step_index == 3
    assert "So what is x" in r.spoken

    r = _turn(engine, r.session, "4")
    assert r.session.step_walk is None
    assert r.session.app_state == AppState.POST_RESPONSE_OPTIONS
    assert r.session.session_progress.problems_correct == 1
    assert "Correct" in r.spoken


def test_wrong_step_response_offers_hint(engine):
    session = drive_to_problem(engine)
    r = _turn(engine, session, "5")
    r = _turn(engine, r.session, "add 6")
    assert r.session.step_walk.step_index == 0  # did not advance
    assert r.session.pending_confirmation == {"type": "step_hint"}
    assert "hint" in r.spoken.lower()


def test_yes_no_hint_confirmation(engine):
    session = drive_to_problem(engine)
    r = _turn(engine, session, "5")
    r = _turn(engine, r.session, "add 6")   # wrong -> hint offered
    r = _turn(engine, r.session, "yes")
    assert r.session.pending_confirmation is None
    assert "undo" in r.spoken.lower() or "opposite" in r.spoken.lower() or "hint" in r.spoken.lower()
    r = _turn(engine, r.session, "no")      # no pending -> gentle re-prompt, no crash
    assert r.session.app_state in (AppState.REASONING,)


def test_stuck_in_step_walk_gets_supportive_hint(engine):
    session = drive_to_problem(engine)
    r = _turn(engine, session, "5")
    r = _turn(engine, r.session, "I don't know")
    assert "That's okay" in r.spoken or "okay" in r.spoken.lower()
    assert r.session.step_walk.step_index == 0


def test_hint_request_in_step_walk(engine):
    session = drive_to_problem(engine)
    r = _turn(engine, session, "5")
    r = _cmd(engine, r.session, IntentKind.REQUEST_HINT)
    assert "Sure" in r.spoken or "hint" in r.spoken.lower()
    assert r.session.app_state == AppState.REASONING


def test_repeated_mistake_escalates_to_solution(engine):
    session = drive_to_problem(engine)
    r = _turn(engine, session, "5")
    for _ in range(4):
        r = _turn(engine, r.session, "add 6")   # wrong each time (attempts climb)
        if r.session.step_walk is None:
            break
        r = _turn(engine, r.session, "no")      # decline the hint, stay on the step
        if r.session.step_walk is None:
            break
    assert r.session.step_walk is None
    assert r.session.app_state == AppState.POST_RESPONSE_OPTIONS
    assert "solution" in r.spoken.lower() or "answer is 4" in r.spoken


def test_show_solution_exits_step_walk(engine):
    session = drive_to_problem(engine)
    r = _turn(engine, session, "5")
    r = _cmd(engine, r.session, IntentKind.SHOW_SOLUTION)
    assert r.session.step_walk is None
    assert r.session.app_state == AppState.POST_RESPONSE_OPTIONS
    assert "Subtract 6 from both sides" in r.spoken


def test_test_mode_has_no_step_walk_and_no_hints(engine):
    session = drive_to_problem(engine)
    session.mode = LearningMode.TEST
    r = _turn(engine, session, "5")
    assert r.session.step_walk is None
    assert r.session.app_state == AppState.INTERVENTION


def test_try_again_restarts_step_question(engine):
    session = drive_to_problem(engine)
    r = _turn(engine, session, "5")
    r = _cmd(engine, r.session, IntentKind.TRY_AGAIN)
    assert r.session.step_walk.step_index == 0
    assert "What should we do with the 6" in r.spoken


def test_next_problem_clears_step_walk(engine):
    session = drive_to_problem(engine)
    r = _turn(engine, session, "5")
    r = _cmd(engine, r.session, IntentKind.NEXT_PROBLEM)
    assert r.session.step_walk is None
    assert r.session.current_problem.problem_id != "alg-le-01"


def test_go_home_clears_step_walk(engine):
    session = drive_to_problem(engine)
    r = _turn(engine, session, "5")
    r = _cmd(engine, r.session, IntentKind.GO_HOME)
    assert r.session.step_walk is None
    assert r.session.app_state == AppState.HOME


def test_correct_reasoning_still_uses_pipeline(engine):
    session = drive_to_problem(engine)
    r = _turn(engine, session, "I subtract 6 from both sides to get 2x equals 8, then divide both sides by 2 to get x equals 4.")
    assert r.session.verification_result.verdict == Verdict.CORRECT
    assert r.session.step_walk is None
    assert r.session.app_state == AppState.POST_RESPONSE_OPTIONS
