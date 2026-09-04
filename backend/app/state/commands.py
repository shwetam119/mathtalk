"""Deterministic intent resolution for voice navigation.

The LLM is never allowed to control application state. Every navigation
decision is resolved here with plain regular expressions, so navigation is
predictable and testable. Open-ended speech is only accepted as mathematical
reasoning while in the REASONING state.
"""
from __future__ import annotations

import re
from typing import List, Optional

from app.mathematics.spoken import WORD_NUMS, words_to_int
from app.models.schemas import AppState, IntentKind, SessionState

_WORD_NUMS = WORD_NUMS


class ParsedIntent:
    def __init__(
        self,
        kind: IntentKind,
        option: Optional[str] = None,
        option_index: Optional[int] = None,
        confidence: float = 1.0,
        matched_text: str = "",
    ):
        self.kind = kind
        self.option = option
        self.option_index = option_index
        self.confidence = confidence
        self.matched_text = matched_text

    def __repr__(self) -> str:  # pragma: no cover
        return f"ParsedIntent(kind={self.kind.value}, option={self.option!r})"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _word_to_int(words: List[str]) -> Optional[int]:
    return words_to_int(words)


# ---------------------------------------------------------------------------
# Global command patterns (checked first)
# ---------------------------------------------------------------------------
_GLOBAL_PATTERNS: List[tuple] = [
    (IntentKind.HELP, r"\b(help|help me|what can i say|what are my options|i need help|need help)\b"),
    (IntentKind.REPEAT, r"\b(repeat|say that again|say it again|again please|repeat that)\b"),
    (IntentKind.GO_BACK, r"\b(go back|back|previous|take me back|go to previous)\b"),
    (IntentKind.GO_HOME, r"\b(go home|home|main menu|take me home|back to home)\b"),
    (IntentKind.STOP, r"\b(stop|pause|stop talking|be quiet|silence)\b"),
    (IntentKind.RESUME, r"\b(resume|continue|continue listening|keep going|unpause)\b"),
    (IntentKind.END_SESSION, r"\b(end session|finish|finish session|end the session|i am done|im done|goodbye|quit)\b"),
]

# Contextual action patterns (matched against the current available actions)
_ACTION_PATTERNS: List[tuple] = [
    (IntentKind.REQUEST_HINT, r"\b(hint|give me a hint|i need a hint|help me start|hint please)\b"),
    (IntentKind.REVIEW_APPROACH, r"\b(review my approach|review my reasoning|what did i do|review approach)\b"),
    (IntentKind.TRY_AGAIN, r"\b(try again|i want to try again|let me try again|retry|attempt again)\b"),
    (IntentKind.SHOW_SOLUTION, r"\b(show the solution|show solution|full solution|tell me the answer|give me the solution|solve it for me)\b"),
    (IntentKind.NEXT_PROBLEM, r"\b(next problem|next question|another problem|next one|skip this problem|give me another)\b"),
    (IntentKind.PRACTICE_MORE, r"\b(practice more|keep practicing|more practice|practice again)\b"),
    (IntentKind.START_NEW_SESSION, r"\b(start new session|new session|start over|restart|new learner)\b"),
]

_YES_PATTERNS = [r"\b(yes|yeah|yep|correct|that's right|thats right|confirm|affirmative|sure)\b"]
_NO_PATTERNS = [r"\b(no|nope|not that|incorrect|wrong option|no that's wrong|no thats wrong)\b"]

_OPTION_NUM_PATTERNS = [
    re.compile(r"^\s*(\d{1,2})\s*[.)]?\s*$"),
    re.compile(r"^\s*option\s+(\d{1,2})\b"),
    re.compile(r"^\s*number\s+(\d{1,2})\b"),
    re.compile(r"^\s*the\s+(\d{1,2})(st|nd|rd|th)\s+option\b"),
    re.compile(r"^\s*choose\s+(\d{1,2})\b"),
    re.compile(r"^\s*select\s+(\d{1,2})\b"),
    re.compile(r"^\s*(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+option\b"),
    re.compile(r"^\s*(?:the\s+)?(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\b"),
]

_ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}

_SELECT_VERBS = r"(select|choose|pick|i choose|i pick|i select|i want|lets do|let's do|go with|try|option|i ll do|i'll do|do)" 


def _match_option_number(text: str) -> Optional[int]:
    t = text.strip().lower()
    for pat in _OPTION_NUM_PATTERNS:
        m = pat.match(t)
        if m:
            g = m.group(1)
            if g in _ORDINALS:
                return _ORDINALS[g]
            if g.isdigit():
                n = int(g)
                if 1 <= n <= 20:
                    return n
            return None
    # word numbers like "one", "option one", "number two"
    m = re.match(r"^\s*(?:option|number|choose|select|pick)?\s*([a-z]+)\s*$", t)
    if m and m.group(1) in _WORD_NUMS:
        v = _WORD_NUMS[m.group(1)]
        if 1 <= v <= 20:
            return v
    m = re.match(r"^\s*(?:option|number)\s+([a-z]+)\s*$", t)
    if m and m.group(1) in _WORD_NUMS:
        v = _WORD_NUMS[m.group(1)]
        if 1 <= v <= 20:
            return v
    return None


def _match_option_name(text: str, actions: List[str]) -> Optional[tuple]:
    """Return (action, index) when the transcript names an available option."""
    t = _norm(text)
    for i, action in enumerate(actions):
        a = _norm(action)
        # "practice" matches action "practice"; "linear equations" matches subtopic
        if a and (a == t or t.startswith(a) or a in t):
            # avoid matching "learn" inside "learning" contexts incorrectly
            if re.search(rf"\b{re.escape(a)}\b", t) or t.startswith(a):
                return action, i
    # stem matching for words like "algebra" vs "algebraic"
    for i, action in enumerate(actions):
        a = _norm(action)
        if a and len(a) > 4 and (t.startswith(a[:6]) or a.startswith(t[:6])):
            return action, i
    return None


def parse_intent(
    transcript: str,
    session: Optional[SessionState] = None,
    extra_actions: Optional[List[str]] = None,
) -> ParsedIntent:
    """Resolve a student utterance to a deterministic intent."""
    text = _norm(transcript)
    if not text:
        return ParsedIntent(IntentKind.UNKNOWN, confidence=0.0, matched_text=transcript)

    # 1. Global commands always win (never let the LLM/ambiguity override them).
    for kind, pat in _GLOBAL_PATTERNS:
        if re.search(pat, text):
            return ParsedIntent(kind, confidence=0.99, matched_text=transcript)

    # 2. Yes / No (for pending confirmations).
    if session and session.pending_confirmation:
        if re.search(_YES_PATTERNS[0], text):
            return ParsedIntent(IntentKind.CONFIRM_YES, confidence=0.99, matched_text=transcript)
        if re.search(_NO_PATTERNS[0], text):
            return ParsedIntent(IntentKind.CONFIRM_NO, confidence=0.99, matched_text=transcript)

    # 3. Contextual action phrases.
    actions = list(extra_actions or [])
    if session:
        actions = list(session.available_actions or [])
    for kind, pat in _ACTION_PATTERNS:
        if re.search(pat, text):
            return ParsedIntent(kind, confidence=0.97, matched_text=transcript)

    # 4. Numbered option ("1", "one", "option one", "first option").
    if session and session.app_state in (
        AppState.HOME, AppState.MODE_SELECTION, AppState.TOPIC_SELECTION,
        AppState.SUBTOPIC_SELECTION, AppState.DIFFICULTY_SELECTION,
        AppState.POST_RESPONSE_OPTIONS, AppState.REVIEW, AppState.END_SESSION,
        AppState.INTERVENTION, AppState.PROBLEM_PRESENTATION,
    ):
        n = _match_option_number(text)
        if n is not None:
            if 1 <= n <= len(actions):
                return ParsedIntent(
                    IntentKind.SELECT_OPTION,
                    option=actions[n - 1],
                    option_index=n - 1,
                    confidence=0.95,
                    matched_text=transcript,
                )
            return ParsedIntent(
                IntentKind.UNKNOWN,
                confidence=0.5,
                matched_text=transcript,
            )

    # 5. Option by name (from available actions).
    if actions:
        hit = _match_option_name(text, actions)
        if hit:
            action, idx = hit
            kind = IntentKind.SELECT_OPTION
            if action.lower() in ("hint", "give me a hint"):
                kind = IntentKind.REQUEST_HINT
            elif action.lower().startswith("try again"):
                kind = IntentKind.TRY_AGAIN
            elif action.lower().startswith("review"):
                kind = IntentKind.REVIEW_APPROACH
            elif action.lower().startswith("show"):
                kind = IntentKind.SHOW_SOLUTION
            elif action.lower().startswith("next"):
                kind = IntentKind.NEXT_PROBLEM
            elif action.lower().startswith("practice more"):
                kind = IntentKind.PRACTICE_MORE
            elif action.lower().startswith("end session"):
                kind = IntentKind.END_SESSION
            elif action.lower().startswith("start new"):
                kind = IntentKind.START_NEW_SESSION
            elif action.lower().startswith("learn"):
                kind = IntentKind.SELECT_OPTION
            return ParsedIntent(kind, option=action, option_index=idx, confidence=0.9, matched_text=transcript)

    # 6. Open-ended speech: accepted as reasoning in REASONING state, and
    #    also right after an intervention (the student may self-correct
    #    immediately instead of first saying "try again").
    if session and session.app_state in (AppState.REASONING, AppState.INTERVENTION):
        return ParsedIntent(IntentKind.SUBMIT_REASONING, confidence=0.8, matched_text=transcript)

    return ParsedIntent(IntentKind.UNKNOWN, confidence=0.2, matched_text=transcript)
