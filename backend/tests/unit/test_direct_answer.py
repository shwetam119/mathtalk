"""Direct-answer support: one-word answers verified deterministically."""
from __future__ import annotations

from app.models.schemas import AppState, IntentKind, Verdict
from app.state.commands import ParsedIntent
from tests.conftest import drive_to_problem


def _to_problem(engine, mode="Practice", topic="Algebra", subtopic="Linear Equations", difficulty="Easy"):
    session = drive_to_problem(engine)  # starts at linear-equation problem
    session = engine.sessions.get_or_create(session.student_id)
    engine.start_session(session)
    for option in (mode, topic, subtopic, difficulty):
        parsed = ParsedIntent(IntentKind.SELECT_OPTION, option=option)
        session = engine.handle_intent(session, parsed).session
        engine.sessions.put(session)
    return session


def _turn(engine, session, text):
    r = engine.handle_turn(session, text, source="text")
    engine.sessions.put(r.session)
    return r


def test_one_word_numeric_answer(engine):
    session = drive_to_problem(engine)  # alg-le-01: 2x + 6 = 14
    r = _turn(engine, session, "4")
    assert r.session.verification_result.verdict == Verdict.CORRECT
    assert r.session.app_state == AppState.POST_RESPONSE_OPTIONS
    assert r.session.input_type == "DIRECT_ANSWER"
    assert r.session.extracted_answer == "4"
    # positive confirmation, never an interrogation
    assert (
        "correct" in r.spoken.lower()
        or "right" in r.spoken.lower()
        or "nice work" in r.spoken.lower()
        or "exactly" in r.spoken.lower()
    )
    assert "how did you get" not in r.spoken.lower()


def test_one_word_spoken_answer(engine):
    session = drive_to_problem(engine)
    r = _turn(engine, session, "four")
    assert r.session.verification_result.verdict == Verdict.CORRECT


def test_variable_phrase_answer(engine):
    session = drive_to_problem(engine)
    r = _turn(engine, session, "x equals four")
    assert r.session.verification_result.verdict == Verdict.CORRECT


def test_wrong_direct_answer_enters_step_focus(engine):
    session = drive_to_problem(engine)
    r = _turn(engine, session, "5")
    assert r.session.verification_result.verdict == Verdict.INCORRECT
    assert r.session.step_walk is not None
    assert r.session.step_walk.step_index == 0
    # step-focused, not an interrogation, not the full solution
    assert "What should we do with the 6" in r.spoken
    assert "how did you get" not in r.spoken.lower()


def test_fraction_answer_spoken_word(engine):
    session = _to_problem(engine, "Practice", "Fractions", "Adding Fractions", "Easy")
    assert session.current_problem.problem_id == "frac-add-01"  # 1/2 + 1/4
    r = _turn(engine, session, "three quarters")
    assert r.session.verification_result.verdict == Verdict.CORRECT


def test_fraction_decimal_equivalence(engine):
    session = _to_problem(engine, "Practice", "Fractions", "Adding Fractions", "Easy")
    r = _turn(engine, session, "0.75")
    assert r.session.verification_result.verdict == Verdict.CORRECT


def test_symbolic_equivalence_expansion(engine):
    session = _to_problem(engine, "Practice", "Algebra", "Simplifying Expressions", "Medium")
    assert session.current_problem.problem_id == "alg-simp-02"  # 2(x + 3)
    r = _turn(engine, session, "2x + 6")
    assert r.session.verification_result.verdict == Verdict.CORRECT
    r = _turn(engine, session, "2(x + 3)")
    assert r.session.verification_result.verdict == Verdict.CORRECT


def test_correct_answer_does_not_force_reasoning(engine):
    session = drive_to_problem(engine)
    r = _turn(engine, session, "4")
    assert r.session.app_state == AppState.POST_RESPONSE_OPTIONS
    assert "how did you get there" not in r.spoken.lower()
    assert "explain" not in r.spoken.lower()


def test_incorrect_answer_does_not_ask_how(engine):
    session = drive_to_problem(engine)
    r = _turn(engine, session, "5")
    assert "how did you get" not in r.spoken.lower()
    # does not reveal the full solution immediately
    assert "The answer is 4" not in r.spoken


def test_direct_answer_uses_verifier_not_strings(engine):
    # "10" is wrong for 2x+6=14 even though it appears in the problem
    session = drive_to_problem(engine)
    r = _turn(engine, session, "10")
    assert r.session.verification_result.verdict == Verdict.INCORRECT
