"""Speech-to-text abstraction.

Primary STT provider for the demo is the browser Web Speech API (real speech
recognition, no credentials, Chrome/Edge/Safari). The frontend owns the
microphone and sends the resulting transcript to the backend through the same
state machine as typed text.

An optional server-side provider (OpenAI-compatible ``/audio/transcriptions``)
is available when STT_API_KEY is configured; it is used the same way.
"""
from __future__ import annotations

from typing import List, Optional

import httpx

from app.core.config import Settings, settings
from app.core.logging import get_logger

log = get_logger("mathtalk.stt")


class STTUnavailable(Exception):
    pass


class STTService:
    def __init__(self, conf: Optional[Settings] = None):
        conf = conf or settings
        self.provider = conf.stt_provider or "browser_web_speech_api"
        self.base_url = conf.stt_base_url.rstrip("/")
        self.api_key = conf.stt_api_key
        self.model = conf.stt_model
        self.timeout = conf.stt_timeout_seconds

    @property
    def is_configured(self) -> bool:
        return bool(self.provider == "openai_compatible" and self.api_key)

    def provider_info(self) -> dict:
        missing: List[str] = []
        if self.provider == "openai_compatible" and not self.api_key:
            missing.append("STT_API_KEY")
        return {
            "provider": self.provider,
            "configured": self.is_configured,
            "missing": missing,
            "note": (
                "Browser Web Speech API (no credentials needed)."
                if self.provider == "browser_web_speech_api"
                else "Server-side transcription via OpenAI-compatible endpoint."
            ),
        }

    def transcribe(self, audio_bytes: bytes, filename: str = "audio.webm") -> str:
        if not self.is_configured:
            raise STTUnavailable("Server-side STT is not configured.")
        files = {"file": (filename, audio_bytes, "audio/webm")}
        data = {"model": self.model}
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    f"{self.base_url}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    data=data,
                    files=files,
                )
            if resp.status_code >= 400:
                raise STTUnavailable(f"STT HTTP {resp.status_code}: {resp.text[:200]}")
            return resp.json().get("text", "")
        except STTUnavailable:
            raise
        except Exception as exc:
            raise STTUnavailable(str(exc)) from exc
