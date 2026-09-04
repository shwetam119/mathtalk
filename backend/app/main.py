"""MathTalk backend — FastAPI application entrypoint."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import PROJECT_ROOT, Settings, settings
from app.core.logging import get_logger, setup_logging
from app.reasoning.classifier import InputClassifier
from app.reasoning.interpreter import ReasoningInterpreter
from app.reasoning.misconception import MisconceptionDetector
from app.services.engine import MathTalkEngine
from app.services.llm import LLMService
from app.services.memory import QdrantMemoryService
from app.services.rime import RimeService
from app.services.stt import STTService
from app.state.sessions import SessionManager
from app.tutoring.policy import TutoringPolicy
from app.tutoring.responses import ResponseGenerator

setup_logging()
log = get_logger("mathtalk.main")


def build_engine(conf: Settings = settings) -> dict:
    """Construct the wired application services (used by app and tests)."""
    memory = QdrantMemoryService(conf)
    llm = LLMService(conf)
    rime = RimeService(conf)
    stt = STTService(conf)
    sessions = SessionManager(conf.data_path)
    interpreter = ReasoningInterpreter(llm_service=llm)
    detector = MisconceptionDetector()
    policy = TutoringPolicy(max_attempts_before_solution=conf.max_attempts_before_solution)
    responses = ResponseGenerator()
    classifier = InputClassifier(llm=llm)
    engine = MathTalkEngine(
        sessions=sessions,
        memory=memory,
        interpreter=interpreter,
        detector=detector,
        policy=policy,
        responses=responses,
        classifier=classifier,
        llm=llm,
        conf=conf,
    )
    return {
        "memory": memory,
        "llm": llm,
        "rime": rime,
        "stt": stt,
        "sessions": sessions,
        "engine": engine,
        "settings": conf,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    services = build_engine()
    for key, value in services.items():
        setattr(app.state, key, value)
    mem = services["memory"]
    log.info(
        "MathTalk ready. memory=%s (%s) | rime=%s | llm=%s | stt=%s",
        mem.provider,
        mem.provider_info()["reason"],
        "configured" if services["rime"].configured else "NOT_CONFIGURED",
        services["llm"].provider,
        services["stt"].provider,
    )
    yield


app = FastAPI(
    title="MathTalk",
    version=settings.version,
    description="Voice-first, reasoning-aware, memory-augmented mathematics learning environment.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:5173", "http://127.0.0.1:5173", "null"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

# Serve the built frontend when present (production/demo mode).
_dist = PROJECT_ROOT / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")


@app.get("/")
def root():
    return {"app": "MathTalk", "docs": "/docs", "health": "/api/health"}
