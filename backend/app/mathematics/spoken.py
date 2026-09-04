"""Deterministic spoken-mathematics understanding.

Converts natural spoken math ("negative five", "three quarters", "x equals
four", "two point five") into a canonical, SymPy-parseable form, and extracts
short direct answers ("4", "four", "x is 4", "the answer is five") without
requiring full sentences.

This layer is intentionally deterministic: it is the fast path that keeps
voice interaction responsive. Gemma is only consulted for genuinely ambiguous
input, and SymPy remains the mathematical authority.
"""
from __future__ import annotations

import re
from typing import List, Optional

from app.models.schemas import DirectAnswer, InputType

# ---------------------------------------------------------------------------
# Word -> number tables (shared with the command parser and interpreter)
# ---------------------------------------------------------------------------
WORD_NUMS: dict = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
}

_TENS = ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_ONES = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]

# fraction unit words: "three quarters" -> 3/4
FRACTION_UNITS: dict = {
    "half": 2, "halves": 2, "third": 3, "thirds": 3, "quarter": 4, "quarters": 4,
    "fourth": 4, "fourths": 4, "fifth": 5, "fifths": 5, "sixth": 6, "sixths": 6,
    "seventh": 7, "sevenths": 7, "eighth": 8, "eighths": 8, "ninth": 9, "ninths": 9,
    "tenth": 10, "tenths": 10, "twelfth": 12, "twelfths": 12,
}

FRACTIONS: dict = {
    "one half": "1/2", "a half": "1/2", "half": "1/2",
    "one third": "1/3", "two thirds": "2/3",
    "one quarter": "1/4", "a quarter": "1/4", "quarter": "1/4", "two quarters": "2/4",
    "one fourth": "1/4", "three fourths": "3/4",
    "one fifth": "1/5", "two fifths": "2/5", "three fifths": "3/5",
    "one sixth": "1/6", "five sixths": "5/6",
    "one eighth": "1/8", "three eighths": "3/8", "five eighths": "5/8", "seven eighths": "7/8",
    "one twelfth": "1/12",
    # hyphenated variants ("three-fourths")
    "one-half": "1/2", "one-third": "1/3", "two-thirds": "2/3",
    "one-quarter": "1/4", "three-quarters": "3/4", "one-fourth": "1/4",
    "three-fourths": "3/4", "three-eighths": "3/8", "five-eighths": "5/8",
}


def words_to_int(words: List[str]) -> Optional[int]:
    """Parse a list of english number words like ['twenty','five'] -> 25."""
    total = 0
    current = 0
    for w in words:
        if w not in WORD_NUMS:
            return None
        v = WORD_NUMS[w]
        if v == 100:
            current = (current or 1) * 100
        elif v >= 20:
            current += v
        else:
            current += v
        if w == "hundred":
            total += current
            current = 0
    total += current
    return total if total > 0 else None


def _expand_hyphenated(text: str) -> str:
    for tens in _TENS:
        for ones in _ONES:
            text = re.sub(
                rf"\b{tens}-{ones}\b",
                str(WORD_NUMS[tens] + WORD_NUMS[ones]),
                text,
            )
    return text


def _expand_word_numbers(text: str) -> str:
    """Replace english number words with digits (longest first)."""
    # compound tens+ones with a space: "twenty five" -> 25 (also "twenty-five")
    for tens in _TENS:
        for ones in _ONES:
            text = re.sub(
                rf"\b{tens}\s+{ones}\b",
                str(WORD_NUMS[tens] + WORD_NUMS[ones]),
                text,
            )
    for w in sorted(WORD_NUMS, key=len, reverse=True):
        text = re.sub(rf"\b{w}\b", str(WORD_NUMS[w]), text)
    return text


def _expand_fractions(text: str) -> str:
    for phrase, value in FRACTIONS.items():
        text = re.sub(rf"\b{re.escape(phrase)}\b", value, text)
    # generic "N eighths" / "N halves" style
    def _unit(m: re.Match) -> str:
        word, unit = m.group(1), m.group(2)
        if word not in WORD_NUMS:
            return m.group(0)
        n = WORD_NUMS[word]
        if n == 1 and unit.endswith("s"):
            unit = unit[:-1]
        return f"{n}/{FRACTION_UNITS[unit]}"
    units = "|".join(sorted(FRACTION_UNITS, key=len, reverse=True))
    text = re.sub(rf"\b(\w+)\s+({units})\b", _unit, text)
    return text


def _clean_symbols(text: str) -> str:
    text = text.replace("÷", "/").replace("×", "*").replace("−", "-").replace("–", "-")
    # keep decimal points; drop other sentence punctuation
    text = re.sub(r"[,\u2019;!?]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_spoken_math(text: str) -> str:
    """Normalize natural spoken math into a canonical parseable form.

    Examples:
        "four"                 -> "4"
        "negative five"        -> "-5"
        "minus five"           -> "-5"
        "two point five"       -> "2.5"
        "three quarters"       -> "3/4"
        "three-fourths"        -> "3/4"
        "twenty five percent"  -> "25/100"
        "x equals four"        -> "x = 4"
        "two x plus four"      -> "2x + 4"
        "three x minus two"    -> "3x - 2"
        "2x equals 8"          -> "2x = 8"
    """
    t = " " + text.lower() + " "
    t = _expand_fractions(t)
    t = _expand_hyphenated(t)
    # word numbers -> digits (before decimal/negative/percent patterns)
    t = _expand_word_numbers(t)
    # decimals: "2 point 5"
    t = re.sub(r"\b(\d+)\s+point\s+(\d+)\b", r"\1.\2", t)
    # negative numbers ("negative five" anywhere; "minus five" only at the start)
    t = re.sub(r"\bnegative\s+(\d+(?:/\d+)?)\b", r"-\1", t)
    t = re.sub(r"^\s*minus\s+(\d+(?:/\d+)?)\b", r"-\1", t)
    # percent
    t = re.sub(r"\b(\d+(?:\.\d+)?)\s+percent\b", r"\1/100", t)
    # variable equations: "x equals 4" / "x is 4" / "2x equals 8"
    t = re.sub(r"\b((?:\d+)?x)\s+(?:equals|is|=)\s+(-?\d+(?:/\d+)?)\b", r"\1 = \2", t)
    # coefficient-variable spacing: "2 x" -> "2x"
    t = re.sub(r"(\d)\s+x\b", r"\1x", t)
    # operator words -> symbols
    t = re.sub(r"\bplus\b", "+", t)
    t = re.sub(r"\bminus\b", "-", t)
    t = re.sub(r"\btimes\b", "*", t)
    t = re.sub(r"\bdivided by\b", "/", t)
    t = re.sub(r"\bover\b", "/", t)
    t = re.sub(r"\b(\d+(?:/\d+)?)\s+over\s+(\d+(?:/\d+)?)\b", r"\1/\2", t)
    return _clean_symbols(t)


# ---------------------------------------------------------------------------
# Direct answer detection
# ---------------------------------------------------------------------------
_ANSWER_PREFIX = re.compile(
    r"^\s*(?:the answer (?:is|would be)|my answer (?:is|would be)|i (?:think|believe|guess|got|get)"
    r"|i think it(?:'s| is)|i got|it(?:'s| is)|so|that(?:'s| is)|which is|answer is|equals|is)\s*"
)
_ANSWER_SUFFIX = re.compile(r"\s*(?:i think|i guess|maybe|probably|approximately|about|roughly)\s*$")

_ANSWER_TOKEN = re.compile(
    r"-?\d+(?:\.\d+)?(?:/\d+)?x?|(?:-?\d+)?x(?:[+*-]\d+)?|[a-z]\s*=\s*-?\d+(?:/\d+)?"
)

# words that should never be treated as a direct answer
_NON_ANSWER_WORDS = re.compile(
    r"\b(hint|help|repeat|back|home|stop|pause|resume|continue|next|solution|answer\s*$|"
    r"explain|review|practice|learn|test|skip|don'?t know|stuck|confused|how|why|what|"
    r"question|problem|again|end|start|yes|no|yeah|nope|should|would|can|me)\b"
)

# multi-clause reasoning sentences are NOT direct answers
_REASONING_CONNECTORS = re.compile(
    r"\b(to get|and then|then (?:divide|add|subtract|multiply|i)|because|so then|after that|"
    r"first |next |i would|i will|i can|i should|both sides|step by step|minus from|from both)\b"
)

# explicit answer phrasings that allow longer utterances: "the answer is 5", "I got 4"
_EXPLICIT_ANSWER = re.compile(
    r"(?:the\s+)?(?:answer|result)\s+is\s+" + r"([-\w./]+)" + r"|"
    r"i\s+(?:got|get|think|believe|guess)\s+" + r"([-\w./]+)" + r"|"
    r"i\s+think\s+it'?s\s+" + r"([-\w./]+)" + r"|"
    r"it'?s\s+" + r"([-\w./]+)"
)

# "x is 4" / "x equals four" (whole utterance begins with the variable)
_EXPLICIT_VARIABLE = re.compile(r"^\s*x\s+(?:equals|is|=|is equal to)\s+" + r"([-\w./]+)" + r"\s*$")

_TRUE_FALSE = {"true": "true", "false": "false"}


def _strip_fillers(text: str) -> str:
    t = text.lower().strip()
    while True:
        m = _ANSWER_PREFIX.match(t)
        if not m:
            break
        t = t[m.end():].strip()
    t = _ANSWER_SUFFIX.sub("", t)
    return t.strip(" .,;:!?\t\n")


def _extract_value(raw: str, value: str) -> Optional[DirectAnswer]:
    """Normalize an extracted answer value into a DirectAnswer."""
    norm = normalize_spoken_math(value)
    # variable equation: "x = 4"
    m = re.match(r"^\s*([a-z])\s*=\s*(-?\d+(?:/\d+)?)\s*$", norm)
    if m:
        return DirectAnswer(
            input_type=InputType.DIRECT_ANSWER,
            answer_expression=m.group(2),
            answer_variable=m.group(1),
            confidence=0.96,
            source="deterministic",
            raw_text=raw,
        )
    # short symbolic expressions: "2x + 6", "5x", "3x - 2"
    if re.match(r"^-?\d*(?:\.\d+)?x(?:\s*[+*-]\s*\d+(?:/\d+)?)*$|^-?\d+\s*[+*-]\s*\d*x(?:\s*[+*-]\s*\d+)*$", norm):
        return DirectAnswer(
            input_type=InputType.DIRECT_ANSWER,
            answer_expression=norm,
            confidence=0.94,
            source="deterministic",
            raw_text=raw,
        )
    if not re.match(r"^-?\d+(?:\.\d+)?(?:/\d+)?x?$", norm):
        return None
    return DirectAnswer(
        input_type=InputType.DIRECT_ANSWER,
        answer_expression=norm,
        confidence=0.95,
        source="deterministic",
        raw_text=raw,
    )


def extract_direct_answer(text: str) -> Optional[DirectAnswer]:
    """Extract a short direct answer from speech.

    Returns None when the text does not look like a direct answer — the caller
    then treats the input as reasoning, a question, or unknown.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    low = raw.lower().strip()
    stripped = _strip_fillers(raw)
    if not stripped:
        return None
    if _NON_ANSWER_WORDS.search(stripped):
        return None

    # multi-clause reasoning sentences are never direct answers
    if _REASONING_CONNECTORS.search(low):
        return None

    # lone boolean answers ("true" / "false")
    if stripped in _TRUE_FALSE:
        return DirectAnswer(
            input_type=InputType.DIRECT_ANSWER,
            answer_expression=_TRUE_FALSE[stripped],
            confidence=0.97,
            source="deterministic",
            raw_text=raw,
        )

    # "x is 4" / "x equals four" (whole utterance begins with the variable)
    m = _EXPLICIT_VARIABLE.match(low)
    if m:
        da = _extract_value(raw, m.group(1))
        if da:
            da.answer_variable = "x"
            return da

    # explicit answer phrasings may be longer: "the answer is five", "I got 4"
    m = _EXPLICIT_ANSWER.search(low)
    if m:
        value = next((g for g in m.groups() if g), None)
        if value:
            da = _extract_value(raw, value)
            if da:
                return da

    # bare short utterances only ("4", "four", "negative five", "three eighths")
    words = stripped.split()
    if len(words) > 6:
        return None

    norm = normalize_spoken_math(stripped)

    # lone variable ("x")
    if norm == "x":
        return DirectAnswer(
            input_type=InputType.DIRECT_ANSWER,
            answer_expression="x",
            confidence=0.9,
            source="deterministic",
            raw_text=raw,
        )

    # variable equation: "x = 4"
    m = re.match(r"^\s*([a-z])\s*=\s*(-?\d+(?:/\d+)?)\s*$", norm)
    if m:
        return DirectAnswer(
            input_type=InputType.DIRECT_ANSWER,
            answer_expression=m.group(2),
            answer_variable=m.group(1),
            confidence=0.96,
            source="deterministic",
            raw_text=raw,
        )

    # short symbolic expressions: "2x + 6", "5x", "3x - 2"
    if re.match(r"^-?\d*(?:\.\d+)?x(?:\s*[+*-]\s*\d+(?:/\d+)?)*$|^-?\d+\s*[+*-]\s*\d*x(?:\s*[+*-]\s*\d+)*$", norm):
        return DirectAnswer(
            input_type=InputType.DIRECT_ANSWER,
            answer_expression=norm,
            confidence=0.94,
            source="deterministic",
            raw_text=raw,
        )

    tokens = re.findall(_ANSWER_TOKEN, norm)
    tokens = [t for t in tokens if t]
    if not tokens:
        return None
    answer = tokens[-1]
    answer = re.sub(r"(\d)x$", r"\1x", answer)
    return DirectAnswer(
        input_type=InputType.DIRECT_ANSWER,
        answer_expression=answer,
        confidence=0.95,
        source="deterministic",
        raw_text=raw,
    )


# ---------------------------------------------------------------------------
# Operation matching for guided step responses ("Subtract." -> subtract)
# ---------------------------------------------------------------------------
_OPERATION_SYNONYMS: dict = {
    "add": ["add", "addition", "plus", "adding"],
    "subtract": ["subtract", "subtraction", "minus", "take away", "takeaway", "remove"],
    "multiply": ["multiply", "multiplication", "times", "multiplying", "product"],
    "divide": ["divide", "division", "dividing", "split"],
}

_NEGATION = re.compile(r"\b(not|don'?t|never|shouldn'?t|wrong|incorrect)\b")


def match_operation(text: str, accepted: Optional[List[str]] = None) -> Optional[str]:
    """Match a spoken step response to a mathematical operation.

    Returns the canonical operation ("add" | "subtract" | "multiply" |
    "divide") when the text expresses it, else None.
    """
    t = " " + (text or "").lower().strip(" .,;:!?\t\n") + " "
    if _NEGATION.search(t):
        return None
    t = re.sub(r"\b(?:by|both sides|the|of|we|should|would|do|i|you|from|to|with)\b", " ", t)
    t = re.sub(r"-?\d+(?:/\d+)?", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    accepted = accepted or list(_OPERATION_SYNONYMS)
    for op, synonyms in _OPERATION_SYNONYMS.items():
        if op not in accepted:
            continue
        for syn in synonyms:
            if re.search(rf"\b{re.escape(syn)}\b", t):
                return op
    return None
