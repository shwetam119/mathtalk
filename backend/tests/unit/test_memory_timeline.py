"""Memory timeline tests: the read-only cross-session misconception timeline.

The timeline endpoint reconstructs past occurrences of one misconception type
from stored memory records: the deduplicated MISCONCEPTION record (frequency +
per-occurrence evidence) and SELF_CORRECTION events. Response kind is derived
deterministically — the first occurrence of an active streak had no matching
learner memory (generic response), later ones retrieve it (targeted).
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import router
from app.main import build_engine
from app.models.schemas import MemoryType, Verdict


def _client(tmp_path):
    """Hermetic TestClient wired to a tmp-data-dir service stack."""
    svcs = build_engine(__import__("app.core.config", fromlist=["Settings"]).Settings(
        data_dir=str(tmp_path), confirm_mode_selection=False, _env_file=None
    ))
    test_app = FastAPI()
    for key, value in svcs.items():
        setattr(test_app.state, key, value)
    test_app.include_router(router)
    return TestClient(test_app), svcs


def _seed_occurrences(memory, student_id: str = "student-a") -> None:
    """Two occurrences of inverse_operation (deduped) + one self-correction."""
    base = dict(
        student_id=student_id, concept="linear_equation", topic="Algebra",
        subtopic="Linear Equations", memory_type=MemoryType.MISCONCEPTION,
        description="inverse operation mistake",
        metadata={"misconception_type": "inverse_operation"},
    )
    memory.store_memory(**base, evidence="added 6 to 14", confidence=0.8)
    memory.store_memory(**base, evidence="divided the right-hand side only", confidence=0.9)
    memory.store_memory(
        student_id=student_id, session_id="sess-2", problem_id="alg-le-02",
        source_session="session-2", concept="linear_equation", topic="Algebra",
        subtopic="Linear Equations", memory_type=MemoryType.SELF_CORRECTION,
        description="Self-corrected on alg-le-02: revised an earlier inverse_operation mistake.",
        evidence="corrected=inverse_operation", confidence=0.95,
        metadata={"misconception_type": "inverse_operation"},
    )


def test_list_by_type_filters_and_sorts(memory):
    _seed_occurrences(memory)
    records = memory.list_by_type("student-a", "inverse_operation")
    assert len(records) == 2  # one merged misconception + one self-correction
    miscon = [r for r in records if r.memory_type == MemoryType.MISCONCEPTION]
    assert miscon[0].metadata.get("frequency", 1) == 2
    assert "added 6 to 14" in miscon[0].evidence and "divided the right-hand side" in miscon[0].evidence
    assert [r.timestamp for r in records] == sorted(r.timestamp for r in records)


def test_list_by_type_ignores_other_types(memory):
    _seed_occurrences(memory)
    memory.store_memory(
        student_id="student-a", concept="adding_fractions", memory_type=MemoryType.MISCONCEPTION,
        description="fraction mistake", evidence="x",
        metadata={"misconception_type": "fraction_denominator"},
    )
    assert memory.list_by_type("student-a", "inverse_operation")  # unaffected
    frac = memory.list_by_type("student-a", "fraction_denominator")
    assert len(frac) == 1 and frac[0].metadata["misconception_type"] == "fraction_denominator"


def test_timeline_endpoint_reconstructs_occurrences(tmp_path):
    client, svcs = _client(tmp_path)
    _seed_occurrences(svcs["memory"])
    res = client.get("/api/students/student-a/misconceptions/inverse_operation/timeline")
    assert res.status_code == 200
    body = res.json()
    assert body["student_id"] == "student-a"
    assert body["misconception_type"] == "inverse_operation"
    entries = body["entries"]
    assert len(entries) == 3
    # first occurrence generic, second targeted (memory now exists), self-correction last
    assert [e["response_kind"] for e in entries] == ["generic", "targeted", "self_correction"]
    assert [e["memory_type"] for e in entries] == ["misconception", "misconception", "self_correction"]
    assert entries[0]["detail"] == "added 6 to 14"
    assert entries[1]["detail"] == "divided the right-hand side only"
    assert entries[2]["problem_id"] == "alg-le-02"
    assert entries[2]["session_id"] == "sess-2"
    assert all(e["label"] == "inverse operation" for e in entries)


def test_timeline_empty_for_unseen_type(tmp_path):
    client, svcs = _client(tmp_path)
    _seed_occurrences(svcs["memory"])
    res = client.get("/api/students/student-a/misconceptions/fraction_denominator/timeline")
    assert res.status_code == 200
    assert res.json()["entries"] == []


def test_timeline_is_isolated_per_student(tmp_path):
    client, svcs = _client(tmp_path)
    _seed_occurrences(svcs["memory"], student_id="student-b")
    res = client.get("/api/students/student-a/misconceptions/inverse_operation/timeline")
    assert res.status_code == 200
    assert res.json()["entries"] == []