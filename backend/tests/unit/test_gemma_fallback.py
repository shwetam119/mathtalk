"""Gemma integration + failure fallback.

When the LLM (Gemma) is configured but fails, the application must remain
fully functional on the deterministic engine: commands, direct answers,
verification, tutoring, step walks, and response generation all keep working.
The LLM is never the mathematical authority.
"""
from __future__ import annotations

import pytest

from app.core.config import Settings
from app.main import build_engine
from app.models.schemas import AppState, IntentKind, InputType, Verdict
from app.reasoning.classifier import InputClassifier
from app.reasoning.interpreter import ReasoningInterpreter
from app.services.engine import MathTalkEngine
from app.services.llm import LLMService, LLMUnavailable
from app.state.commands import ParsedIntent
from tests.conftest import drive_to_problem


class BrokenLLM(LLMService):
    """A configured LLM service whose every call fails."""

    def chat(self, *args, **kwargs):
        raise LLMUnavailable("gemma endpoint unreachable (test)")


def _conf():
    return Settings(
        data_dir="/tmp/mt-gemma-test", confirm_mode_selection=False,
        llm_provider="gemma", gemma_api_key="test-key", gemma_model="gemma-test",
        _env_file=None,
    )


@pytest.fixture
def broken_engine():
    conf = _conf()
    svcs = build_engine(conf)
    broken = BrokenLLM(conf)
    interpreter = ReasoningInterpreter(llm_service=broken)
    engine = MathTalkEngine(
        sessions=svcs["sessions"],
        memory=svcs["memory"],
        interpreter=interpreter,
        detector=svcs["engine"].detector,
        policy=svcs["engine"].policy,
        responses=svcs["engine"].responses,
        classifier=InputClassifier(llm=broken),
        llm=broken,
        conf=conf,
    )
    yield engine, broken
    svcs["sessions"].clear_all()
    for sid in ("gemma-student",):
        try:
            svcs["memory"].delete_all_for_student(sid)
        except Exception:
            pass


def _turn(engine, session, text):
    r = engine.handle_turn(session, text, source="text")
    engine.sessions.put(r.session)
    return r


def test_llm_provider_reports_gemma():
    conf = _conf()
    llm = LLMService(conf)
    assert llm.is_configured is True
    assert llm.provider == "gemma"
    assert llm.model == "gemma-test"
    info = llm.provider_info()
    assert info["configured"] is True
    assert info["provider"] == "gemma"


def test_missing_gemma_key_reported():
    conf = Settings(llm_provider="gemma", _env_file=None)
    info = LLMService(conf).provider_info()
    assert info["configured"] is False
    assert "GEMMA_API_KEY" in info["missing"]


def test_interpreter_falls_back_when_gemma_fails(broken_engine):
    engine, broken = broken_engine
    from app.mathematics.problems import find_problem
    from app.models.schemas import Difficulty

    problem = find_problem("Algebra", "Linear Equations", Difficulty.EASY)
    sr = engine.interpreter.interpret(problem, "I add 6 and 14 to get 20 and then divide by 2")
    assert sr.final_answer == "10"
    assert sr.source == "deterministic"


def test_classifier_falls_back_when_gemma_fails(broken_engine):
    engine, broken = broken_engine
    session = engine.sessions.get_or_create("gemma-student", force_new=True)
    engine.start_session(session)
    c = engine.classifier.classify_with_llm("four", session, None)
    assert c.input_type == InputType.DIRECT_ANSWER
    assert c.source == "deterministic"


def test_direct_answer_works_with_broken_gemma(broken_engine):
    engine, broken = broken_engine
    session = drive_to_problem(engine, student_id="gemma-student")
    r = _turn(engine, session, "4")
    assert r.session.verification_result.verdict == Verdict.CORRECT
    assert "correct" in r.spoken.lower() or "nice work" in r.spoken.lower() or "right" in r.spoken.lower()


def test_reasoning_and_step_walk_work_with_broken_gemma(broken_engine):
    engine, broken = broken_engine
    session = drive_to_problem(engine, student_id="gemma-student")
    r = _turn(engine, session, "5")
    assert r.session.step_walk is not None
    assert "What should we do with the 6" in r.spoken


def test_response_polish_falls_back_to_deterministic(broken_engine):
    engine, broken = broken_engine
    session = engine.sessions.get_or_create("gemma-student", force_new=True)
    engine.start_session(session)
    polished = engine._polish(session, None, "Deterministic tutor message.")
    assert polished == "Deterministic tutor message."


def test_broken_llm_never_crashes_commands(broken_engine):
    engine, broken = broken_engine
    session = engine.sessions.get_or_create("gemma-student", force_new=True)
    engine.start_session(session)
    r = engine.handle_intent(session, ParsedIntent(IntentKind.HELP))
    assert r.ok is True
    assert "what you can say" in r.spoken.lower() or "help" in r.spoken.lower()
