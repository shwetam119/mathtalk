"""Rime TTS integration — the primary speech-output system.

When RIME_API_KEY is set, the real Rime API is used and the audio is returned
to the frontend for playback. When credentials are missing, the service reports
exactly what is missing; the frontend then falls back to browser speech
synthesis and clearly labels it as a fallback (MathTalk never claims Rime is
working when it is not).
"""
from __future__ import annotations

import base64
import re
from typing import List, Optional, Tuple

import httpx

from app.core.config import Settings, settings
from app.core.logging import get_logger

log = get_logger("mathtalk.rime")


class RimeUnavailable(Exception):
    pass


class RimeService:
    def __init__(self, conf: Optional[Settings] = None):
        conf = conf or settings
        self.api_key = conf.rime_api_key
        self.api_url = conf.rime_api_url
        self.speaker = conf.rime_speaker
        self.model_id = conf.rime_model_id
        self.timeout = conf.rime_timeout_seconds

    # ------------------------------------------------------------------
    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def status(self) -> dict:
        missing: List[str] = []
        if not self.api_key:
            missing.append("RIME_API_KEY")
        return {
            "provider": "rime",
            "configured": self.configured,
            "missing": missing,
            "speaker": self.speaker if self.configured else "",
            "model": self.model_id if self.configured else "",
            "note": (
                "Real Rime TTS. Get a key at https://rime.ai and set RIME_API_KEY "
                "(optionally RIME_SPEAKER / RIME_MODEL_ID)."
                if not self.configured
                else "Rime is configured."
            ),
        }

    # ------------------------------------------------------------------
    def _chunk_text(self, text: str, max_len: int = 900) -> List[str]:
        if len(text) <= max_len:
            return [text]
        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks: List[str] = []
        cur = ""
        for s in sentences:
            if len(cur) + len(s) + 1 > max_len and cur:
                chunks.append(cur)
                cur = s
            else:
                cur = f"{cur} {s}".strip()
        if cur:
            chunks.append(cur)
        return chunks

    # ------------------------------------------------------------------
    def synthesize(self, text: str) -> Tuple[bytes, str]:
        """Call Rime and return (audio_bytes, mime_type).

        Raises RimeUnavailable on any failure. The caller decides the
        fallback; this service never fabricates a successful response.
        """
        if not self.configured:
            raise RimeUnavailable(
                "Rime is not configured. Set RIME_API_KEY in the environment."
            )
        chunks = self._chunk_text(text)
        audio = b""
        mime = "audio/wav"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "audio/wav",
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                for chunk in chunks:
                    payload = {"text": chunk, "speaker": self.speaker, "modelId": self.model_id}
                    resp = client.post(self.api_url, headers=headers, json=payload)
                    if resp.status_code >= 400:
                        raise RimeUnavailable(
                            f"Rime HTTP {resp.status_code}: {resp.text[:300]}"
                        )
                    ctype = resp.headers.get("content-type", "")
                    data = resp.content
                    if "json" in ctype or data[:1] == b"{":
                        try:
                            data = base64.b64decode(resp.json().get("audioContent", ""))
                            mime = "audio/wav"
                        except Exception as exc:
                            raise RimeUnavailable(f"Rime returned unexpected JSON: {exc}")
                    audio += data
        except RimeUnavailable:
            raise
        except Exception as exc:
            raise RimeUnavailable(f"Rime request failed: {exc}") from exc

        if not audio:
            raise RimeUnavailable("Rime returned empty audio.")
        return audio, mime
