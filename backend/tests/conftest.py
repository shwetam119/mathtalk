"""Shared fixtures: hermetic settings (tmp data dir), wired services, engine."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings  # noqa: E402
from app.main import build_engine  # noqa: E402


@pytest.fixture
def conf(tmp_path):
    return Settings(data_dir=str(tmp_path), confirm_mode_selection=False, _env_file=None)


@pytest.fixture
def services(conf):
    svcs = build_engine(conf)
    yield svcs
    svcs["sessions"].clear_all()
    for sid in ("student-a", "student-b", "demo-student-001"):
        try:
            svcs["memory"].delete_all_for_student(sid)
        except Exception:
            pass


@pytest.fixture
def engine(services):
    return services["engine"]


@pytest.fixture
def memory(services):
    return services["memory"]


def flawed_for(problem):
    """The canonical flawed reasoning transcript for a linear equation ax + b = c."""
    a, b, c = _linear(problem)
    return f"I add {abs(b)} and {c} to get {abs(b) + c} and then divide by {a}."


def correct_for(problem):
    """The canonical correct reasoning transcript for a linear equation ax + b = c."""
    import re as _re

    a, b, c = _linear(problem)
    if b > 0:
        undo = f"subtract {b} from both sides"
        mid = c - b
    else:
        undo = f"add {abs(b)} to both sides"
        mid = c + abs(b)
    return (
        f"I {undo} to get {a}x equals {mid}, then divide both sides by {a} "
        f"to get x equals {mid // a}."
    )


def _linear(problem):
    import re as _re

    m = _re.match(r"^\s*(\d*)x\s*([+-])\s*(\d+)\s*=\s*(\d+)\s*$", problem.display)
    assert m, f"not a linear equation: {problem.display}"
    a = int(m.group(1)) if m.group(1) else 1
    b = int(m.group(3)) * (1 if m.group(2) == "+" else -1)
    c = int(m.group(4))
    return a, b, c


def drive_to_problem(engine, student_id: str = "student-a"):
    """Drive the voice flow to the first linear-equation problem.

    A new session is started when the previous one ended (END_SESSION), which
    is how Session 2 begins with the same student identity.
    """
    from app.models.schemas import AppState, IntentKind
    from app.state.commands import ParsedIntent

    existing = engine.sessions.get(student_id)
    force_new = existing is not None and existing.app_state == AppState.END_SESSION
    session = engine.sessions.get_or_create(student_id, force_new=force_new)
    engine.start_session(session)
    for option in ("Practice", "Algebra", "Linear Equations", "Easy"):
        parsed = ParsedIntent(IntentKind.SELECT_OPTION, option=option)
        session = engine.handle_intent(session, parsed).session
        engine.sessions.put(session)
    return engine.sessions.get(student_id)
