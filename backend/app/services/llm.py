"""Clean server-side LLM abstraction (OpenAI-compatible, incl. Gemma).

Gemma is integrated here, in the EXISTING LLM abstraction — no Gemma-specific
API calls exist anywhere else in the project. Configure with::

    LLM_PROVIDER=gemma
    GEMMA_MODEL=...        (e.g. your Gemma 4 deployment id)
    GEMMA_API_KEY=...      (or LLM_API_KEY)
    GEMMA_BASE_URL=...     (optional; OpenAI-compatible endpoint)

The LLM is used only for *understanding* (classification, reasoning
interpretation) and *natural wording* (response polish). It can never
override deterministic mathematical verification and it can never change
application state directly.

When no LLM credentials are configured, MathTalk runs on the deterministic
engine (regex interpreter + SymPy + rule-based tutoring) — fully functional,
clearly labelled ``provider=\"deterministic\"``.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import Settings, settings
from app.core.logging import get_logger
from app.models.schemas import Problem, SessionState

log = get_logger("mathtalk.llm")

_JSON_SCHEMA_HINT = (
    "Return ONLY a single JSON object. No markdown, no prose, no code fences."
)


class LLMUnavailable(Exception):
    pass


class LLMService:
    def __init__(self, conf: Optional[Settings] = None):
        conf = conf or settings
        self.provider = (conf.llm_provider or "deterministic").strip().lower()
        if self.provider == "gemma":
            self.base_url = (conf.gemma_base_url or conf.llm_base_url).rstrip("/")
            self.api_key = conf.gemma_api_key or conf.llm_api_key
            self.model = conf.gemma_model or conf.llm_model
        else:
            self.base_url = conf.llm_base_url.rstrip("/")
            self.api_key = conf.llm_api_key
            self.model = conf.llm_model
        self.timeout = conf.llm_timeout_seconds
        self.max_tokens = conf.llm_max_tokens
        self.use_for_responses = conf.llm_use_for_responses

    # ------------------------------------------------------------------
    @property
    def is_configured(self) -> bool:
        return bool(self.provider in ("gemma", "openai_compatible") and self.api_key)

    def provider_info(self) -> dict:
        missing: List[str] = []
        if self.provider and not self.api_key:
            missing.append("GEMMA_API_KEY" if self.provider == "gemma" else "LLM_API_KEY")
        return {
            "provider": self.provider,
            "configured": self.is_configured,
            "model": self.model if self.is_configured else "",
            "missing": missing,
        }

    # ------------------------------------------------------------------
    def chat(self, messages: List[Dict[str, str]], temperature: float = 0.2) -> str:
        if not self.is_configured:
            raise LLMUnavailable("LLM is not configured.")
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": self.max_tokens,
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=body,
                )
            if resp.status_code >= 400:
                raise LLMUnavailable(f"LLM HTTP {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except LLMUnavailable:
            raise
        except Exception as exc:
            raise LLMUnavailable(str(exc)) from exc

    # ------------------------------------------------------------------
    # reasoning interpretation (existing contract, never authoritative)
    # ------------------------------------------------------------------
    def extract_reasoning(self, problem: Problem, transcript: str) -> Dict[str, Any]:
        system = (
            "You are the reasoning-interpretation stage of a mathematics tutoring system. "
            "You convert a student's spoken reasoning into structured JSON. "
            "You are NOT the final mathematical authority — a deterministic verifier checks every claim. "
            'Return ONLY JSON with keys: concept (string), reasoning_pattern (string), '
            'student_actions (array of short canonical action labels like "added_constant_to_rhs", '
            '"subtracted_constant_from_both_sides", "divided_both_sides_by_coefficient", "used_favorable_over_total"), '
            'mathematical_claims (array of {text, expression, expected, operation} where text is like "6 + 14 = 20", '
            'expression is the sympy-parsable left side, expected is the right side or null, '
            'operation is add|subtract|multiply|divide|solve|evaluate), steps (array of strings), '
            "final_answer (string or null), reasoning_quality (sound|flawed|incomplete|ambiguous). "
            + _JSON_SCHEMA_HINT
        )
        user = (
            f"Problem: {problem.prompt} (expected answer {problem.expected_answer})\n"
            f"Student reasoning: {transcript}\n"
            "Extract the structured reasoning JSON now."
        )
        raw = self.chat([{"role": "system", "content": system}, {"role": "user", "content": user}], temperature=0.0)
        return self._parse_json(raw)

    # ------------------------------------------------------------------
    # contextual input classification
    # ------------------------------------------------------------------
    def classify_input(
        self,
        transcript: str,
        session: SessionState,
        problem: Optional[Problem] = None,
    ) -> Dict[str, Any]:
        system = (
            "You classify what a student said in a mathematics tutoring conversation. "
            "Return ONLY JSON with keys: input_type, answer_expression (string, only for DIRECT_ANSWER), "
            "answer_variable (string or null), confidence (0..1), reason (short string). "
            "input_type must be exactly one of: COMMAND, DIRECT_ANSWER, REASONING, QUESTION, "
            "REQUEST_FOR_HELP, REQUEST_FOR_HINT, REQUEST_FOR_REPEAT, CONFIRMATION, REJECTION, "
            "UNCERTAIN, OTHER. "
            "A short number, spoken number, or 'x equals 4' is DIRECT_ANSWER. "
            "'yes'/'no' are CONFIRMATION/REJECTION. 'I don't know'/'I'm stuck' is REQUEST_FOR_HELP. "
            "Multi-step explanations are REASONING. Do not classify every short input as an answer; "
            "use the tutor's current question as context. " + _JSON_SCHEMA_HINT
        )
        context = {
            "app_state": session.app_state.value,
            "tutor_question": session.last_spoken[:400],
            "available_options": session.available_actions,
            "problem": problem.prompt if problem else None,
            "student_input": transcript,
        }
        raw = self.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
            ],
            temperature=0.0,
        )
        return self._parse_json(raw)

    # ------------------------------------------------------------------
    # natural tutor response generation (facts come from the engine)
    # ------------------------------------------------------------------
    def generate_response(self, context: Dict[str, Any]) -> str:
        system = (
            "You are MathTalk, a patient, human mathematics tutor that speaks to a learner by voice. "
            "Use the structured facts provided; you MUST NOT contradict them and MUST NOT invent "
            "mathematical facts. Rules:\n"
            "- Short, concise spoken sentences. One idea at a time. No lists, no markdown, no headers.\n"
            "- Never mention internal systems: no Qdrant, SymPy, verification engine, LLM, or 'the system'.\n"
            "- When the answer is correct, confirm warmly and briefly — do not ask 'how did you get there?'.\n"
            "- When something is wrong, acknowledge briefly and ask ONE targeted next-step question; "
            "never dump the full solution unless instructed.\n"
            "- If the student is stuck, be supportive and give a small next action.\n"
            "- Do not repeat the problem verbatim. Sound human, not robotic.\n"
            "Return ONLY the spoken text, nothing else."
        )
        user = json.dumps(context, ensure_ascii=False)
        raw = self.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.5,
        )
        text = raw.strip()
        text = re.sub(r"^```(?:text)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        if not text or len(text) > 2000:
            raise LLMUnavailable("LLM returned unusable response text.")
        return text

    # ------------------------------------------------------------------
    @staticmethod
    def _parse_json(raw: str) -> Dict[str, Any]:
        cleaned = raw.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            return json.loads(cleaned)
        except Exception:
            m = re.search(r"\{.*\}", cleaned, re.S)
            if m:
                try:
                    return json.loads(m.group(0))
                except Exception:
                    pass
            raise LLMUnavailable("LLM returned unparseable JSON.")
