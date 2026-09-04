"""Central application configuration.

All secrets are read from environment variables (or a root `.env` file).
Nothing secret is ever exposed to the browser or printed to logs.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> project root
PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(PROJECT_ROOT / ".env"), str(PROJECT_ROOT / "backend" / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "MathTalk"
    environment: str = "development"
    version: str = "1.0.0"

    # --- backend server -------------------------------------------------
    backend_host: str = "127.0.0.1"
    backend_port: int = 8020
    frontend_origin: str = "http://localhost:5173"
    # data dir (relative to project root) for local persistence
    data_dir: str = "backend/data"

    # --- LLM (server-side only) ----------------------------------------
    # Leave LLM_API_KEY empty to run the deterministic fallback engine.
    # llm_provider: "gemma" | "openai_compatible" | "" (deterministic)
    llm_provider: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 20.0
    llm_max_tokens: int = 900
    # Gemma-specific overrides (used when llm_provider == "gemma").
    # Any GEMMA_* value falls back to its LLM_* equivalent when unset.
    gemma_api_key: str = ""
    gemma_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    gemma_model: str = "gemma-3-27b-it"
    # Route tutor response wording through the LLM when it is configured.
    llm_use_for_responses: bool = True

    # --- Rime TTS (primary speech output) ------------------------------
    rime_api_key: str = ""
    rime_api_url: str = "https://users.rime.ai/v1/rime-tts"
    rime_speaker: str = "celeste"
    rime_model_id: str = "coda"
    rime_timeout_seconds: float = 30.0

    # --- Qdrant learner memory -----------------------------------------
    # Leave QDRANT_URL empty to run the local (file-backed) memory store.
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    qdrant_collection: str = "mathtalk_learner_memory"
    qdrant_vector_size: int = 64
    qdrant_timeout_seconds: float = 5.0

    # --- Server-side speech-to-text (optional) -------------------------
    # When empty, the browser Web Speech API is the STT provider.
    stt_provider: str = ""  # "openai_compatible" or "" (browser Web Speech API)
    stt_base_url: str = "https://api.openai.com/v1"
    stt_api_key: str = ""
    stt_model: str = "whisper-1"
    stt_timeout_seconds: float = 30.0

    # --- tutoring / demo ------------------------------------------------
    demo_student_id: str = "demo-student-001"
    max_attempts_before_solution: int = 3
    confirm_mode_selection: bool = True
    auto_speak: bool = True

    @property
    def data_path(self) -> Path:
        p = PROJECT_ROOT / self.data_dir
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def rime_missing(self) -> List[str]:
        missing: List[str] = []
        if not self.rime_api_key:
            missing.append("RIME_API_KEY")
        return missing

    @property
    def llm_missing(self) -> List[str]:
        if not self.llm_provider:
            return []
        if self.llm_provider == "gemma":
            return ["GEMMA_API_KEY"] if not (self.gemma_api_key or self.llm_api_key) else []
        return ["LLM_API_KEY"] if not self.llm_api_key else []

    @property
    def stt_missing(self) -> List[str]:
        if self.stt_provider and not self.stt_api_key:
            return ["STT_API_KEY"]
        return []


settings = Settings()
