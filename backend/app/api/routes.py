"""REST API.

All endpoints operate on the single authoritative SessionState via the
conversation engine. The visual dashboard and the voice layer call exactly the
same endpoints.
"""
from __future__ import annotations

import base64
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.models.schemas import IntentKind, MemoryType, TimelineEntry, VoiceStatus
from app.services.rime import RimeUnavailable
from app.state.commands import ParsedIntent

router = APIRouter(prefix="/api")


# --------------------------------------------------------------------------
# request bodies
# --------------------------------------------------------------------------
class StartRequest(BaseModel):
    student_id: str = "demo-student-001"
    force_new: bool = False


class TurnRequest(BaseModel):
    student_id: str = "demo-student-001"
    transcript: str = Field(..., min_length=1)
    source: str = "speech"  # speech | text
    confidence: float = 1.0


class CommandRequest(BaseModel):
    student_id: str = "demo-student-001"
    intent: str
    option: Optional[str] = None


class VoiceStatusRequest(BaseModel):
    student_id: str = "demo-student-001"
    status: str


class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1)


class StudentRequest(BaseModel):
    student_id: str = "demo-student-001"


def _engine(request: Request):
    return request.app.state.engine


def _sessions(request: Request):
    return request.app.state.sessions


def _memory(request: Request):
    return request.app.state.memory


# --------------------------------------------------------------------------
# health / readiness
# --------------------------------------------------------------------------
@router.get("/health")
def health():
    return {"status": "ok", "app": "mathtalk-backend"}


@router.get("/readiness")
def readiness(request: Request):
    memory = request.app.state.memory
    rime = request.app.state.rime
    llm = request.app.state.llm
    stt = request.app.state.stt
    return {
        "status": "ready",
        "services": {
            "memory": memory.provider_info(),
            "rime": rime.status(),
            "llm": llm.provider_info(),
            "stt": stt.provider_info(),
        },
    }


@router.get("/config")
def config(request: Request):
    """Non-secret service configuration for the dashboard."""
    memory = request.app.state.memory
    rime = request.app.state.rime
    llm = request.app.state.llm
    stt = request.app.state.stt
    return {
        "memory": memory.provider_info(),
        "rime": rime.status(),
        "llm": llm.provider_info(),
        "stt": stt.provider_info(),
        "confirm_mode_selection": request.app.state.settings.confirm_mode_selection,
        "version": request.app.state.settings.version,
    }


# --------------------------------------------------------------------------
# session
# --------------------------------------------------------------------------
@router.post("/session/start")
def start_session(body: StartRequest, request: Request):
    engine = _engine(request)
    session = _sessions(request).get_or_create(body.student_id, force_new=body.force_new)
    result = engine.start_session(session)
    _sessions(request).put(result.session)
    return result.to_dict()


@router.get("/session/state")
def get_state(student_id: str = "demo-student-001", request: Request = None):
    session = _sessions(request).get(student_id)
    if session is None:
        raise HTTPException(404, detail="No active session. POST /api/session/start first.")
    return {"state": session.model_dump(mode="json")}


@router.post("/session/turn")
def submit_turn(body: TurnRequest, request: Request):
    engine = _engine(request)
    sessions = _sessions(request)
    session = sessions.get_or_create(body.student_id)
    result = engine.handle_turn(session, body.transcript, source=body.source, confidence=body.confidence)
    sessions.put(result.session)
    return result.to_dict()


@router.post("/session/command")
def submit_command(body: CommandRequest, request: Request):
    """Deterministic intent command (used by buttons/keyboard shortcuts)."""
    engine = _engine(request)
    sessions = _sessions(request)
    session = sessions.get_or_create(body.student_id)
    try:
        kind = IntentKind[body.intent.upper()]
    except KeyError:
        raise HTTPException(422, detail=f"Unknown intent: {body.intent}")
    parsed = ParsedIntent(kind, option=body.option)
    result = engine.handle_intent(session, parsed)
    sessions.put(result.session)
    return result.to_dict()


@router.post("/session/voice-status")
def update_voice_status(body: VoiceStatusRequest, request: Request):
    engine = _engine(request)
    sessions = _sessions(request)
    session = sessions.get_or_create(body.student_id)
    try:
        _ = VoiceStatus(body.status.upper())
    except ValueError:
        raise HTTPException(422, detail=f"Unknown voice status: {body.status}")
    engine.set_voice_status(session, body.status.upper())
    sessions.put(session)
    return {"ok": True}


# --------------------------------------------------------------------------
# voice (Rime TTS)
# --------------------------------------------------------------------------
@router.post("/voice/speak")
def speak(body: SpeakRequest, request: Request):
    rime = request.app.state.rime
    if not rime.configured:
        status = rime.status()
        raise HTTPException(
            503,
            detail={
                "configured": False,
                "provider": "rime",
                "missing": status["missing"],
                "note": status["note"],
            },
        )
    try:
        audio, mime = rime.synthesize(body.text)
    except RimeUnavailable as exc:
        raise HTTPException(502, detail={"configured": True, "error": str(exc)})
    return {
        "provider": "rime",
        "mime": mime,
        "audio": base64.b64encode(audio).decode("ascii"),
    }


@router.get("/voice/status")
def voice_status(request: Request):
    return request.app.state.rime.status()


# --------------------------------------------------------------------------
# learner memory (monitoring + privacy)
# --------------------------------------------------------------------------
@router.get("/memory/{student_id}")
def list_memories(student_id: str, request: Request):
    try:
        records = _memory(request).list_for_student(student_id)
    except Exception as exc:
        raise HTTPException(503, detail=str(exc))
    return {"student_id": student_id, "memories": [r.model_dump(mode="json") for r in records]}


@router.delete("/memory/{student_id}")
def delete_memories(student_id: str, request: Request):
    try:
        count = _memory(request).delete_all_for_student(student_id)
    except Exception as exc:
        raise HTTPException(503, detail=str(exc))
    return {"deleted": True, "student_id": student_id, "count": count}


@router.get("/students/{student_id}/misconceptions/{misconception_type}/timeline")
def misconception_timeline(student_id: str, misconception_type: str, request: Request):
    """Past occurrences of one misconception type for a student (read-only).

    Occurrences are reconstructed from stored memory records: the deduplicated
    MISCONCEPTION record carries one evidence snippet per occurrence (frequency
    counts them), and each SELF_CORRECTION event is its own occurrence. Because
    the tutoring policy is deterministic — the first occurrence of an active
    streak has no matching learner memory yet (generic response) while later
    occurrences in the same streak retrieve it (targeted, memory-based
    response) — each occurrence node is tagged accordingly.
    """
    try:
        records = _memory(request).list_by_type(student_id, misconception_type)
    except Exception as exc:
        raise HTTPException(503, detail=str(exc))

    entries: List[TimelineEntry] = []
    for rec in records:
        if rec.memory_type == MemoryType.MISCONCEPTION:
            parts = [p.strip() for p in rec.evidence.split("|") if p.strip()] if rec.evidence else []
            count = max(len(parts), int(rec.metadata.get("frequency", 1)))
            occurrences = parts + [""] * (count - len(parts))
            for i, part in enumerate(occurrences):
                entries.append(TimelineEntry(
                    session_id=rec.session_id or rec.source_session,
                    problem_id=rec.problem_id,
                    label=misconception_type.replace("_", " "),
                    memory_type=rec.memory_type.value,
                    response_kind="generic" if i == 0 else "targeted",
                    timestamp=rec.timestamp,
                    detail=part,
                ))
        elif rec.memory_type == MemoryType.SELF_CORRECTION:
            entries.append(TimelineEntry(
                session_id=rec.session_id or rec.source_session,
                problem_id=rec.problem_id,
                label=misconception_type.replace("_", " "),
                memory_type=rec.memory_type.value,
                response_kind="self_correction",
                timestamp=rec.timestamp,
                detail=rec.description,
            ))
    return {
        "student_id": student_id,
        "misconception_type": misconception_type,
        "entries": [e.model_dump(mode="json") for e in entries],
    }


# --------------------------------------------------------------------------
# demo controls
# --------------------------------------------------------------------------
@router.post("/demo/reset")
def demo_reset(body: StudentRequest, request: Request):
    """Reset a demo learner: sessions + all Qdrant/local memories."""
    student_id = body.student_id
    sessions = _sessions(request)
    sessions.reset_student(student_id)
    try:
        _memory(request).delete_all_for_student(student_id)
    except Exception as exc:
        raise HTTPException(503, detail=str(exc))
    return {"reset": True, "student_id": student_id}
