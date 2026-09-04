"""Learner-memory tests: store, retrieve, dedupe, resolve, delete, isolation."""
from __future__ import annotations

import pytest

from app.models.schemas import MemoryStatus, MemoryType
from app.services.memory import QdrantMemoryService


@pytest.fixture
def svc(conf, tmp_path):
    s = QdrantMemoryService(conf)
    yield s
    try:
        s.delete_all_for_student("student-a")
        s.delete_all_for_student("student-b")
    except Exception:
        pass


def test_store_and_retrieve(svc):
    rec = svc.store_memory(
        student_id="student-a",
        concept="linear_equation",
        topic="Algebra",
        memory_type=MemoryType.MISCONCEPTION,
        description="inverse operation",
        evidence="added 6 to 14",
        confidence=0.9,
        metadata={"misconception_type": "inverse_operation"},
    )
    assert rec.memory_id
    hits = svc.retrieve_relevant_memories("student-a", query_text="adding instead of subtracting", concept="linear_equation")
    assert hits, "retrieval must find the stored memory"
    assert hits[0].student_id == "student-a"


def test_student_isolation(svc):
    svc.store_memory(
        student_id="student-a", concept="linear_equation", memory_type=MemoryType.MISCONCEPTION,
        description="A's secret mistake", evidence="x", metadata={"misconception_type": "inverse_operation"},
    )
    hits_b = svc.retrieve_relevant_memories("student-b", query_text="A's secret mistake")
    assert hits_b == []
    listed_b = svc.list_for_student("student-b")
    assert all(r.student_id == "student-b" for r in listed_b)


def test_misconception_dedupe(svc):
    kwargs = dict(
        student_id="student-a", concept="linear_equation", topic="Algebra",
        memory_type=MemoryType.MISCONCEPTION, description="inverse operation",
        evidence="first", confidence=0.8, metadata={"misconception_type": "inverse_operation"},
    )
    r1 = svc.store_memory(**kwargs)
    kwargs["evidence"] = "second"
    r2 = svc.store_memory(**kwargs)
    assert r1.memory_id == r2.memory_id, "duplicate misconception memories must be merged"
    assert r2.metadata.get("frequency", 1) == 2
    assert "second" in r2.evidence


def test_update_and_resolve(svc):
    rec = svc.store_memory(
        student_id="student-a", concept="fractions", memory_type=MemoryType.MISCONCEPTION,
        description="denominator", evidence="x", metadata={"misconception_type": "fraction_denominator"},
    )
    updated = svc.update_memory(rec.memory_id, confidence=0.99)
    assert updated.confidence == 0.99
    resolved = svc.mark_memory_resolved(rec.memory_id)
    assert resolved.status == MemoryStatus.RESOLVED


def test_delete_memory(svc):
    rec = svc.store_memory(
        student_id="student-a", concept="probability", memory_type=MemoryType.ATTEMPT,
        description="attempt", evidence="x",
    )
    assert svc.delete_memory(rec.memory_id) is True
    assert svc.get_memory(rec.memory_id) is None


def test_delete_all_for_student(svc):
    for i in range(3):
        svc.store_memory(
            student_id="student-a", concept=f"concept-{i}", memory_type=MemoryType.ATTEMPT,
            description=f"memory {i}", evidence="x",
        )
    svc.delete_all_for_student("student-a")
    assert svc.list_for_student("student-a") == []


def test_provider_info_is_honest(svc):
    info = svc.provider_info()
    assert info["provider"] in ("qdrant", "local")
    assert "reason" in info


def test_retrieval_scoring_orders_by_relevance(svc):
    svc.store_memory(
        student_id="student-a", concept="linear_equation", memory_type=MemoryType.MISCONCEPTION,
        description="inverse operations with equations", evidence="added instead of subtracting",
        metadata={"misconception_type": "inverse_operation"},
    )
    svc.store_memory(
        student_id="student-a", concept="probability", memory_type=MemoryType.MISCONCEPTION,
        description="adding probabilities", evidence="added independent events",
        metadata={"misconception_type": "adding_probabilities"},
    )
    hits = svc.retrieve_relevant_memories(
        "student-a", query_text="inverse operations solving equations", concept="linear_equation"
    )
    assert hits[0].concept == "linear_equation"
    assert hits[0].score >= hits[-1].score
