"""Persistent learner memory.

Primary integration is a real Qdrant server (HTTP API). When Qdrant is not
configured or unreachable, a file-backed local vector store with the identical
interface is used so the learning loop (store -> retrieve -> change behavior)
still runs and can be tested. The active backend is always reported honestly
through ``provider_info()``.
"""
from __future__ import annotations

import hashlib
import json
import math
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

import httpx

from app.core.config import Settings, settings
from app.core.logging import get_logger
from app.models.schemas import MemoryRecord, MemoryStatus, MemoryType

log = get_logger("mathtalk.memory")


class MemoryUnavailable(Exception):
    """Raised when the active memory backend cannot fulfil an operation."""


def _embed(tokens: List[str], size: int) -> List[float]:
    """Deterministic feature-hash embedding (no external model required)."""
    vec = [0.0] * size
    for tok in tokens:
        for w in tok.replace("_", " ").split():
            h = hashlib.md5(w.encode("utf-8")).digest()
            idx = int.from_bytes(h[:4], "big") % size
            sign = 1.0 if h[4] % 2 == 0 else -1.0
            vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _record_tokens(record: MemoryRecord) -> List[str]:
    toks = [
        record.concept,
        record.memory_type.value,
        record.topic,
        record.subtopic,
        record.description,
        record.evidence,
    ]
    if record.metadata.get("misconception_type"):
        toks.append(str(record.metadata["misconception_type"]))
    return toks


def _stable_int(memory_id: str) -> int:
    return int.from_bytes(hashlib.md5(memory_id.encode()).digest()[:8], "big") % (2 ** 63)


class _LocalBackend:
    """File-backed in-process vector store with the same interface as Qdrant."""

    provider = "local"

    def __init__(self, path: Path, vector_size: int):
        self.path = path
        self.vector_size = vector_size
        self._lock = threading.RLock()
        self._records: Dict[str, MemoryRecord] = {}
        self._vectors: Dict[str, List[float]] = {}
        self._load()

    # -- persistence -----------------------------------------------------
    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text("utf-8"))
                for item in data:
                    rec = MemoryRecord(**item["record"])
                    self._records[rec.memory_id] = rec
                    self._vectors[rec.memory_id] = item["vector"]
            except Exception as exc:  # pragma: no cover
                log.warning("Could not load local memory file: %s", exc)

    def _save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = [
                {"record": rec.model_dump(mode="json"), "vector": self._vectors[rec.memory_id]}
                for rec in self._records.values()
            ]
            self.path.write_text(json.dumps(data, indent=1), "utf-8")

    # -- operations -------------------------------------------------------
    def upsert(self, record: MemoryRecord) -> MemoryRecord:
        with self._lock:
            self._records[record.memory_id] = record
            self._vectors[record.memory_id] = _embed(_record_tokens(record), self.vector_size)
            self._save()
        return record

    def search(self, student_id: str, query: List[str], limit: int, memory_type: Optional[str]) -> List[MemoryRecord]:
        with self._lock:
            qv = _embed(query, self.vector_size)
            scored = []
            for rec in self._records.values():
                if rec.student_id != student_id:
                    continue
                if memory_type and rec.memory_type.value != memory_type:
                    continue
                v = self._vectors.get(rec.memory_id)
                if not v:
                    continue
                score = sum(a * b for a, b in zip(qv, v))
                r = rec.model_copy(deep=True)
                r.score = float(score)
                scored.append(r)
            scored.sort(key=lambda r: (r.score or -1), reverse=True)
            return scored[:limit]

    def get(self, memory_id: str) -> Optional[MemoryRecord]:
        with self._lock:
            rec = self._records.get(memory_id)
            return rec.model_copy(deep=True) if rec else None

    def delete(self, memory_id: str) -> bool:
        with self._lock:
            ok = memory_id in self._records
            self._records.pop(memory_id, None)
            self._vectors.pop(memory_id, None)
            if ok:
                self._save()
            return ok

    def delete_by_student(self, student_id: str) -> int:
        with self._lock:
            ids = [mid for mid, r in self._records.items() if r.student_id == student_id]
            for mid in ids:
                self._records.pop(mid, None)
                self._vectors.pop(mid, None)
            if ids:
                self._save()
            return len(ids)

    def all_for_student(self, student_id: str) -> List[MemoryRecord]:
        with self._lock:
            return [r.model_copy(deep=True) for r in self._records.values() if r.student_id == student_id]


class _QdrantBackend:
    """Real Qdrant server client over its HTTP API."""

    provider = "qdrant"

    def __init__(self, base_url: str, api_key: str, collection: str, vector_size: int, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.collection = collection
        self.vector_size = vector_size
        self.timeout = timeout
        self._headers = {"Content-Type": "application/json"}
        if api_key:
            self._headers["api-key"] = api_key

    def _url(self, path: str) -> str:
        return f"{self.base_url}/collections/{self.collection}{path}"

    def _req(self, method: str, path: str, body: Optional[dict] = None) -> dict:
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.request(method, self._url(path), headers=self._headers, json=body)
            if resp.status_code >= 400:
                raise MemoryUnavailable(f"Qdrant {method} {path} -> HTTP {resp.status_code}: {resp.text[:200]}")
            return resp.json() if resp.content else {}

    def ping(self) -> bool:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                r = client.get(f"{self.base_url}/collections", headers=self._headers)
            return r.status_code < 400
        except Exception:
            return False

    def ensure_collection(self) -> None:
        try:
            info = self._req("GET", "")
            if "result" not in info:
                raise MemoryUnavailable("unexpected qdrant response")
            return
        except MemoryUnavailable:
            pass
        body = {
            "vectors": {"size": self.vector_size, "distance": "Cosine"},
            "on_disk_payload": True,
        }
        self._req("PUT", "", body)

    def upsert(self, record: MemoryRecord) -> MemoryRecord:
        self.ensure_collection()
        vec = _embed(_record_tokens(record), self.vector_size)
        point = {
            "id": _stable_int(record.memory_id),
            "vector": vec,
            "payload": {"memory_id": record.memory_id, **record.model_dump(mode="json")},
        }
        self._req("PUT", "/points?wait=true", {"points": [point]})
        return record

    def search(self, student_id: str, query: List[str], limit: int, memory_type: Optional[str]) -> List[MemoryRecord]:
        self.ensure_collection()
        vec = _embed(query, self.vector_size)
        must: List[dict] = [{"key": "student_id", "match": {"value": student_id}}]
        if memory_type:
            must.append({"key": "memory_type", "match": {"value": memory_type}})
        body = {"vector": vec, "limit": limit, "filter": {"must": must}, "with_payload": True}
        resp = self._req("POST", "/points/search", body)
        results = []
        for hit in resp.get("result", []):
            payload = hit.get("payload") or {}
            rec = MemoryRecord(**{k: v for k, v in payload.items() if k != "memory_id"})
            rec.score = float(hit.get("score", 0.0))
            results.append(rec)
        return results

    def get(self, memory_id: str) -> Optional[MemoryRecord]:
        hits = self.search_by_payload({"memory_id": memory_id}, 1)
        return hits[0] if hits else None

    def search_by_payload(self, match: Dict[str, str], limit: int = 10) -> List[MemoryRecord]:
        self.ensure_collection()
        must = [{"key": k, "match": {"value": v}} for k, v in match.items()]
        body = {"filter": {"must": must}, "limit": limit, "with_payload": True}
        resp = self._req("POST", "/points/scroll", body)
        out = []
        for hit in resp.get("result", {}).get("points", []):
            payload = hit.get("payload") or {}
            out.append(MemoryRecord(**{k: v for k, v in payload.items() if k != "memory_id"}))
        return out

    def delete(self, memory_id: str) -> bool:
        self.ensure_collection()
        self._req("POST", "/points/delete", {
            "filter": {"must": [{"key": "memory_id", "match": {"value": memory_id}}]}
        })
        return True

    def delete_by_student(self, student_id: str) -> int:
        self.ensure_collection()
        self._req("POST", "/points/delete", {
            "filter": {"must": [{"key": "student_id", "match": {"value": student_id}}]}
        })
        return -1  # qdrant does not report count

    def all_for_student(self, student_id: str) -> List[MemoryRecord]:
        return self.search_by_payload({"student_id": student_id}, limit=100)


class QdrantMemoryService:
    """Learner-memory facade. Voice and visual interfaces both use this."""

    def __init__(self, conf: Optional[Settings] = None):
        conf = conf or settings
        self.vector_size = conf.qdrant_vector_size
        self._backend: object = None
        self._reason = ""
        if conf.qdrant_url:
            q = _QdrantBackend(
                conf.qdrant_url, conf.qdrant_api_key, conf.qdrant_collection,
                conf.qdrant_vector_size, conf.qdrant_timeout_seconds,
            )
            if q.ping():
                self._backend = q
                self._reason = "qdrant_connected"
            else:
                self._reason = "qdrant_unreachable"
                log.warning("QDRANT_URL is set but Qdrant is unreachable at %s — using local memory store.", conf.qdrant_url)
        if self._backend is None:
            self._backend = _LocalBackend(conf.data_path / "memory_local.json", conf.qdrant_vector_size)
            if not self._reason:
                self._reason = "qdrant_not_configured"

    @property
    def provider(self) -> str:
        return getattr(self._backend, "provider", "unknown")

    def provider_info(self) -> dict:
        return {"provider": self.provider, "reason": self._reason, "vector_size": self.vector_size}

    # ------------------------------------------------------------------
    def _safe(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except MemoryUnavailable:
            raise
        except Exception as exc:
            log.error("Memory backend error: %s", exc)
            raise MemoryUnavailable(str(exc)) from exc

    def store_memory(
        self,
        *,
        student_id: str,
        session_id: str = "",
        problem_id: str = "",
        source_session: str = "",
        concept: str = "",
        topic: str = "",
        subtopic: str = "",
        memory_type: MemoryType,
        description: str,
        evidence: str = "",
        confidence: float = 0.0,
        metadata: Optional[dict] = None,
    ) -> MemoryRecord:
        """Store a memory; deduplicates active misconception memories."""
        metadata = metadata or {}
        # Dedupe: an active misconception memory for the same student+concept+type
        # is updated (evidence grows, frequency increases) instead of duplicated.
        if memory_type == MemoryType.MISCONCEPTION:
            existing = self.retrieve_relevant_memories(
                student_id,
                query_text=description,
                memory_type=MemoryType.MISCONCEPTION.value,
                concept_filter=metadata.get("misconception_type") or concept,
                limit=5,
            )
            for rec in existing:
                if (
                    rec.status == MemoryStatus.ACTIVE
                    and rec.concept == concept
                    and rec.metadata.get("misconception_type") == metadata.get("misconception_type")
                ):
                    rec.confidence = max(rec.confidence, confidence)
                    rec.evidence = f"{rec.evidence} | {evidence}" if evidence else rec.evidence
                    rec.metadata["frequency"] = rec.metadata.get("frequency", 1) + 1
                    rec.metadata["last_session"] = session_id
                    rec.timestamp = time.time()
                    return self._safe(self._backend.upsert, rec)

        rec = MemoryRecord(
            student_id=student_id,
            session_id=session_id,
            problem_id=problem_id,
            source_session=source_session,
            concept=concept,
            topic=topic,
            subtopic=subtopic,
            memory_type=memory_type,
            description=description,
            evidence=evidence,
            confidence=confidence,
            metadata=metadata,
        )
        return self._safe(self._backend.upsert, rec)

    def retrieve_relevant_memories(
        self,
        student_id: str,
        query_text: str = "",
        concept: str = "",
        memory_type: Optional[str] = None,
        limit: int = 5,
        concept_filter: Optional[str] = None,
    ) -> List[MemoryRecord]:
        tokens = [query_text, concept, concept_filter or ""]
        return self._safe(self._backend.search, student_id, tokens, limit, memory_type)

    def get_memory(self, memory_id: str) -> Optional[MemoryRecord]:
        return self._safe(self._backend.get, memory_id)

    def update_memory(self, memory_id: str, **fields) -> Optional[MemoryRecord]:
        rec = self.get_memory(memory_id)
        if rec is None:
            return None
        for k, v in fields.items():
            if hasattr(rec, k):
                setattr(rec, k, v)
        rec.timestamp = time.time()
        return self._safe(self._backend.upsert, rec)

    def mark_memory_resolved(self, memory_id: str) -> Optional[MemoryRecord]:
        return self.update_memory(memory_id, status=MemoryStatus.RESOLVED)

    def delete_memory(self, memory_id: str) -> bool:
        return self._safe(self._backend.delete, memory_id)

    def delete_all_for_student(self, student_id: str) -> int:
        return self._safe(self._backend.delete_by_student, student_id)

    def list_for_student(self, student_id: str) -> List[MemoryRecord]:
        return self._safe(self._backend.all_for_student, student_id)

    def list_by_type(self, student_id: str, misconception_type: str, limit: int = 50) -> List[MemoryRecord]:
        """All stored records for a student that carry the given misconception type.

        Covers MISCONCEPTION records (deduplicated across occurrences — each
        occurrence appends its evidence, joined by " | ", and bumps `frequency`)
        and SELF_CORRECTION events (one record per correction). Sorted oldest ->
        newest. Read-only, additive helper for the timeline endpoint.
        """
        recs = [
            r for r in self.list_for_student(student_id)
            if r.metadata.get("misconception_type") == misconception_type
        ]
        recs.sort(key=lambda r: r.timestamp)
        return recs[-limit:] if limit else recs
