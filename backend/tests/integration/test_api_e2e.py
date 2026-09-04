"""End-to-end HTTP test driving the full learner workflow through the API.

This mirrors exactly what the voice/visual frontend does: start -> select ->
problem -> flawed reasoning -> diagnosis -> hint -> self-correct -> session 2.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import router
from app.main import build_engine

STUDENT = "api-demo-student"


@pytest.fixture
def client(conf):
    app = FastAPI()
    services = build_engine(conf)
    for key, value in services.items():
        setattr(app.state, key, value)
    app.include_router(router)
    with TestClient(app) as c:
        yield c
    services["sessions"].clear_all()
    try:
        services["memory"].delete_all_for_student(STUDENT)
    except Exception:
        pass


def _post(client, path, **json):
    r = client.post(path, json=json)
    assert r.status_code == 200, (path, r.text)
    return r.json()


def _get(client, path, **params):
    r = client.get(path, params=params)
    assert r.status_code == 200, (path, r.text)
    return r.json()


def _select(client, option):
    return _post(client, "/api/session/command", student_id=STUDENT, intent="select_option", option=option)


def _turn(client, text):
    return _post(client, "/api/session/turn", student_id=STUDENT, transcript=text, source="speech")


def _flawed(problem):
    """Canonical flawed reasoning for a linear equation display like '2x + 6 = 14'."""
    import re

    m = re.match(r"^\s*(\d*)x\s*([+-])\s*(\d+)\s*=\s*(\d+)\s*$", problem["display"])
    a = int(m.group(1)) if m.group(1) else 1
    b = int(m.group(3))
    c = int(m.group(4))
    return f"I add {b} and {c} to get {b + c} and then divide by {a}."


def _correct(problem):
    import re

    m = re.match(r"^\s*(\d*)x\s*([+-])\s*(\d+)\s*=\s*(\d+)\s*$", problem["display"])
    a = int(m.group(1)) if m.group(1) else 1
    sign = m.group(2)
    b = int(m.group(3))
    c = int(m.group(4))
    if sign == "+":
        mid = c - b
        undo = f"subtract {b} from both sides"
    else:
        mid = c + b
        undo = f"add {b} to both sides"
    return f"I {undo} to get {a}x equals {mid}, then divide both sides by {a} to get x equals {mid // a}."


def test_health_and_readiness(client):
    assert client.get("/api/health").json()["status"] == "ok"
    rd = _get(client, "/api/readiness")
    assert rd["status"] == "ready"
    assert rd["services"]["memory"]["provider"] in ("qdrant", "local")
    assert rd["services"]["rime"]["configured"] is False
    assert "RIME_API_KEY" in rd["services"]["rime"]["missing"]


def test_voice_speak_requires_credentials(client):
    r = client.post("/api/voice/speak", json={"text": "hello"})
    assert r.status_code == 503
    body = r.json()["detail"]
    assert body["configured"] is False
    assert "RIME_API_KEY" in body["missing"]


def test_full_workflow_session1_and_session2(client):
    # ---- launch ----
    start = _post(client, "/api/session/start", student_id=STUDENT)
    assert start["state"]["app_state"] == "HOME"
    assert "Welcome to MathTalk" in start["spoken"]

    # ---- navigate by voice ----
    r = _select(client, "Practice")
    assert r["state"]["app_state"] == "TOPIC_SELECTION"
    r = _select(client, "Algebra")
    assert r["state"]["app_state"] == "SUBTOPIC_SELECTION"
    r = _select(client, "Linear Equations")
    assert r["state"]["app_state"] == "DIFFICULTY_SELECTION"
    r = _select(client, "Easy")
    assert r["state"]["app_state"] == "REASONING"
    problem = r["state"]["current_problem"]
    assert problem["problem_id"] == "alg-le-01"

    # ---- flawed reasoning ----
    r = _turn(client, _flawed(problem))
    state = r["state"]
    assert state["app_state"] == "INTERVENTION"
    assert state["misconception"]["misconception_type"] == "inverse_operation"
    assert state["selected_intervention"]["memory_based"] is False
    stages = [e["stage"] for e in r["pipeline_events"]]
    for s in ("stt", "interpreter", "verifier", "misconception", "memory", "policy", "response"):
        assert s in stages
    assert "Not quite" in r["spoken"]

    # ---- hint ----
    r = _post(client, "/api/session/command", student_id=STUDENT, intent="request_hint")
    assert r["state"]["app_state"] == "REASONING"
    assert r["state"]["assistance_level"] == 2

    # ---- self-correct ----
    r = _turn(client, _correct(problem))
    assert r["state"]["app_state"] == "POST_RESPONSE_OPTIONS"
    assert r["state"]["verification_result"]["verdict"] == "correct"
    assert r["state"]["session_progress"]["problems_correct"] == 1

    # ---- memory stored ----
    mem = _get(client, f"/api/memory/{STUDENT}")
    types = {m["memory_type"] for m in mem["memories"]}
    assert "misconception" in types
    assert "strength" in types

    # ---- end session, start session 2 ----
    r = _post(client, "/api/session/command", student_id=STUDENT, intent="end_session")
    assert r["state"]["app_state"] == "END_SESSION"
    r = _post(client, "/api/session/command", student_id=STUDENT, intent="start_new_session")
    assert r["state"]["app_state"] == "HOME"
    assert r["state"]["session_number"] == 2

    # ---- session 2: same learner, related problem ----
    _select(client, "Practice")
    _select(client, "Algebra")
    _select(client, "Linear Equations")
    r = _select(client, "Easy")
    problem2 = r["state"]["current_problem"]
    assert problem2["problem_id"] != "alg-le-01"

    # ---- same flawed reasoning: memory must change behavior ----
    r = _turn(client, _flawed(problem2))
    iv = r["state"]["selected_intervention"]
    assert iv["memory_based"] is True, "Session 2 must be memory-based"
    assert iv["type"] == "targeted_intervention"
    assert "inverse" in iv["message"]
    assert any(
        m["metadata"].get("misconception_type") == "inverse_operation"
        for m in r["state"]["retrieved_memories"]
    )

    # ---- student self-corrects ----
    r = _turn(client, _correct(problem2))
    assert r["state"]["verification_result"]["verdict"] == "correct"


def test_demo_reset_clears_everything(client):
    start = _post(client, "/api/session/start", student_id=STUDENT)
    _select(client, "Practice")
    _select(client, "Algebra")
    _select(client, "Linear Equations")
    r = _select(client, "Easy")
    _turn(client, _flawed(r["state"]["current_problem"]))
    assert len(_get(client, f"/api/memory/{STUDENT}")["memories"]) > 0

    r = _post(client, "/api/demo/reset", student_id=STUDENT)
    assert r["reset"] is True
    assert _get(client, f"/api/memory/{STUDENT}")["memories"] == []

    # a fresh session starts at HOME (no stale state)
    start = _post(client, "/api/session/start", student_id=STUDENT)
    assert start["state"]["app_state"] == "HOME"
    assert start["state"]["session_number"] == 1


def test_memory_deletion_endpoint(client):
    _post(client, "/api/session/start", student_id=STUDENT)
    _select(client, "Practice")
    _select(client, "Algebra")
    _select(client, "Linear Equations")
    r = _select(client, "Easy")
    _turn(client, _flawed(r["state"]["current_problem"]))
    r = client.delete(f"/api/memory/{STUDENT}")
    assert r.status_code == 200
    assert _get(client, f"/api/memory/{STUDENT}")["memories"] == []


def test_student_isolation_via_api(client):
    other = "other-student"
    try:
        _post(client, "/api/session/start", student_id=STUDENT)
        _select(client, "Practice")
        _select(client, "Algebra")
        _select(client, "Linear Equations")
        r = _select(client, "Easy")
        _turn(client, _flawed(r["state"]["current_problem"]))
        mem_other = _get(client, f"/api/memory/{other}")
        assert mem_other["memories"] == []
    finally:
        client.delete(f"/api/memory/{other}")


def test_recovery_paths(client):
    # empty transcript
    r = client.post("/api/session/turn", json={"student_id": STUDENT, "transcript": "  ", "source": "speech"})
    assert r.status_code == 200
    assert "didn't hear" in r.json()["spoken"].lower()
    # unknown command
    r = client.post("/api/session/command", json={"student_id": STUDENT, "intent": "nonsense"})
    assert r.status_code == 422
    # unknown voice status
    r = client.post("/api/session/voice-status", json={"student_id": STUDENT, "status": "banana"})
    assert r.status_code == 422


def _drive_to_linear(client, difficulty="Easy"):
    """Start a session and navigate to the first linear-equation problem."""
    _post(client, "/api/session/start", student_id=STUDENT, force_new=True)
    _select(client, "Practice")
    _select(client, "Algebra")
    _select(client, "Linear Equations")
    r = _select(client, difficulty)
    return r["state"]["current_problem"]


def test_one_word_direct_answer_correct(client):
    problem = _drive_to_linear(client)
    r = _turn(client, "4")
    state = r["state"]
    assert state["input_type"] == "DIRECT_ANSWER"
    assert state["extracted_answer"] == "4"
    assert state["verification_result"]["verdict"] == "correct"
    assert state["app_state"] == "POST_RESPONSE_OPTIONS"
    assert (
        "correct" in r["spoken"].lower()
        or "right" in r["spoken"].lower()
        or "nice work" in r["spoken"].lower()
        or "exactly" in r["spoken"].lower()
    )
    assert "how did you get" not in r["spoken"].lower()


def test_spoken_word_direct_answer_correct(client):
    _drive_to_linear(client)
    r = _turn(client, "four")
    assert r["state"]["verification_result"]["verdict"] == "correct"


def test_wrong_answer_starts_step_walk_demo(client):
    problem = _drive_to_linear(client)
    # wrong one-word answer -> step-focused guidance
    r = _turn(client, "5")
    state = r["state"]
    assert state["input_type"] == "DIRECT_ANSWER"
    assert state["step_walk"]["step_index"] == 0
    assert "What should we do with the 6" in r["spoken"]

    # step by step
    r = _turn(client, "Subtract.")
    assert r["state"]["step_walk"]["step_index"] == 1
    r = _turn(client, "2x equals 8")
    assert r["state"]["step_walk"]["step_index"] == 2
    r = _turn(client, "divide by 2")
    assert r["state"]["step_walk"]["step_index"] == 3
    r = _turn(client, "4")
    state = r["state"]
    assert state["step_walk"] is None
    assert state["app_state"] == "POST_RESPONSE_OPTIONS"
    assert state["session_progress"]["problems_correct"] == 1
    assert "Correct" in r["spoken"]


def test_stuck_student_gets_supportive_response(client):
    _drive_to_linear(client)
    r = _turn(client, "I don't know")
    assert r["state"]["input_type"] == "REQUEST_FOR_HELP"
    assert "okay" in r["spoken"].lower() or "take" in r["spoken"].lower()


def test_hint_in_step_walk_via_api(client):
    _drive_to_linear(client)
    _turn(client, "5")
    r = _post(client, "/api/session/command", student_id=STUDENT, intent="request_hint")
    assert r["state"]["app_state"] == "REASONING"
    assert "hint" in r["spoken"].lower() or "undo" in r["spoken"].lower()


def test_reasoning_input_still_runs_full_pipeline(client):
    problem = _drive_to_linear(client)
    r = _turn(client, _flawed(problem))
    state = r["state"]
    assert state["input_type"] == "REASONING"
    assert state["app_state"] == "INTERVENTION"
    assert state["misconception"]["misconception_type"] == "inverse_operation"
    stages = [e["stage"] for e in r["pipeline_events"]]
    assert "classifier" in stages
    for s in ("interpreter", "verifier", "misconception", "memory", "policy"):
        assert s in stages
