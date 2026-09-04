"""Session manager.

One authoritative ``SessionState`` per active student. The voice interface and
the visual dashboard read and modify the very same object — there is no
duplicated state anywhere.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Dict, Optional

from app.models.schemas import SessionState


class SessionManager:
    def __init__(self, data_path: Path):
        self.data_path = data_path
        self._sessions: Dict[str, SessionState] = {}
        self._counters: Dict[str, int] = {}
        self._lock = threading.RLock()
        self._counter_file = data_path / "session_counters.json"
        self._load_counters()

    # ------------------------------------------------------------------
    def _load_counters(self) -> None:
        if self._counter_file.exists():
            try:
                self._counters = json.loads(self._counter_file.read_text("utf-8"))
            except Exception:
                self._counters = {}

    def _save_counters(self) -> None:
        self.data_path.mkdir(parents=True, exist_ok=True)
        self._counter_file.write_text(json.dumps(self._counters, indent=1), "utf-8")

    def _next_session_number(self, student_id: str) -> int:
        with self._lock:
            n = self._counters.get(student_id, 0) + 1
            self._counters[student_id] = n
            self._save_counters()
            return n

    # ------------------------------------------------------------------
    def get(self, student_id: str) -> Optional[SessionState]:
        with self._lock:
            s = self._sessions.get(student_id)
            return s.model_copy(deep=True) if s else None

    def get_or_create(self, student_id: str, force_new: bool = False) -> SessionState:
        with self._lock:
            existing = self._sessions.get(student_id)
            if existing is not None and not force_new:
                return existing.model_copy(deep=True)
            number = self._next_session_number(student_id)
            session = SessionState(student_id=student_id, session_number=number)
            self._sessions[student_id] = session
            return session.model_copy(deep=True)

    def put(self, session: SessionState) -> None:
        with self._lock:
            self._sessions[session.student_id] = session.model_copy(deep=True)

    def end(self, student_id: str) -> None:
        with self._lock:
            self._sessions.pop(student_id, None)

    def reset_student(self, student_id: str) -> None:
        """Remove in-memory session state (memories are handled separately)."""
        with self._lock:
            self._sessions.pop(student_id, None)
            self._counters.pop(student_id, None)
            self._save_counters()

    def clear_all(self) -> None:
        with self._lock:
            self._sessions.clear()
            self._counters.clear()
            self._save_counters()
