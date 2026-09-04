"""Reasoning interpreter.

Turns the student's natural-language reasoning into structured mathematical
claims. A deterministic extractor always runs; an LLM (when configured) may
produce a richer semantic interpretation, but every mathematical claim is
still verified deterministically afterwards. The LLM is never the authority.
"""
from __future__ import annotations

import json
import re
from fractions import Fraction
from typing import Dict, List, Optional, Tuple

from app.mathematics.spoken import FRACTIONS, FRACTION_UNITS, WORD_NUMS
from app.models.schemas import DirectAnswer, MathClaim, Problem, StructuredReasoning

_OPERATOR_SYMBOL = {
    "add": "+",
    "subtract": "-",
    "multiply": "*",
    "divide": "/",
}

_FRACTION_UNITS = FRACTION_UNITS
_FRACTIONS = FRACTIONS
_NUM_WORDS = dict(WORD_NUMS)

_RESULT_PATTERN = re.compile(
    r"(?:to get|gets|equals|is equal to|is|gives|which is|that gives|leaving|giving)\s+"
    r"(-?\d+(?:/\d+)?)(?!x)"
)

_PHRASES: List[Tuple[str, re.Pattern]] = [
    ("add", re.compile(r"\badd\s+(-?\d+(?:/\d+)?)\s+(?:and|to|plus)\s+(-?\d+(?:/\d+)?)\b")),
    ("add", re.compile(r"\b(-?\d+(?:/\d+)?)\s+plus\s+(-?\d+(?:/\d+)?)\b")),
    ("subtract", re.compile(r"\bsubtract\s+(-?\d+(?:/\d+)?)\s+from\s+(-?\d+(?:/\d+)?)\b")),
    ("subtract", re.compile(r"\bsubtract\s+(-?\d+(?:/\d+)?)\s+from\s+(?:both sides|each side|both the sides)\b")),
    ("subtract", re.compile(r"\b(-?\d+(?:/\d+)?)\s+minus\s+(-?\d+(?:/\d+)?)\b")),
    ("multiply", re.compile(r"\bmultiply\s+(-?\d+(?:/\d+)?)\s+by\s+(-?\d+(?:/\d+)?)\b")),
    ("multiply", re.compile(r"\b(-?\d+(?:/\d+)?)\s+times\s+(-?\d+(?:/\d+)?)\b")),
    ("multiply", re.compile(r"\b(-?\d+(?:/\d+)?)\s+multiplied\s+by\s+(-?\d+(?:/\d+)?)\b")),
    ("divide", re.compile(r"\bdivide\s+(-?\d+(?:/\d+)?)\s+by\s+(-?\d+(?:/\d+)?)\b")),
    ("divide", re.compile(r"\b(-?\d+(?:/\d+)?)\s+divided\s+by\s+(-?\d+(?:/\d+)?)\b")),
    ("divide", re.compile(r"\bdivide\s+(?:both sides|each side|both the sides)\s+by\s+(-?\d+(?:/\d+)?)\b")),
    ("divide", re.compile(r"\bdivide\s+by\s+(-?\d+(?:/\d+)?)\b")),
    ("divide", re.compile(r"\b(-?\d+(?:/\d+)?)\s+over\s+(-?\d+(?:/\d+)?)\b")),
]

_SOLVE_ANSWER = re.compile(
    r"\b(?:the answer is|so x is|answer is|so the answer is|therefore x is|meaning x is|which means x is|"
    r"so x equals|therefore x equals)\s+(-?\d+(?:/\d+)?)"
)
_SOLVE_X = re.compile(r"\b(?:x|the variable)\s+(?:equals|is|=)\s+(-?\d+(?:/\d+)?)\b")
_EQUATION_WITH_OP = re.compile(
    r"\b([0-9]+x|[0-9]+\s*x)\s*(?:plus|minus|\+|-)\s*(\d+)\s*(?:equals|is|=)\s*(-?\d+(?:/\d+)?)\b"
)
_EQUATION_X_EQ = re.compile(r"\b([0-9]+x|[0-9]+\s*x)\s*(?:equals|is|=)\s*(-?\d+(?:/\d+)?)\b")
_EQUATION_UNLIKE = re.compile(
    r"\b([0-9]+x|[0-9]+\s*x)\s*(?:plus|minus|\+|\-)\s*(\d+)\s*(?:equals|is|=)\s*([0-9]+x|[0-9]+\s*x)\b"
)


def _frac_value(s: str) -> Optional[Fraction]:
    try:
        return Fraction(s)
    except Exception:
        return None


def _render_frac(f: Fraction) -> str:
    if f.denominator == 1:
        return str(f.numerator)
    return f"{f.numerator}/{f.denominator}"


def digitize(text: str) -> str:
    """Normalize spoken numbers/fractions/operators into a parseable form."""
    t = " " + text.lower() + " "
    t = re.sub(r"[.,;!?]+", " ", t)
    for k, v in _FRACTIONS.items():
        t = re.sub(rf"\b{re.escape(k)}\b", v, t)
    # generic "N eighths" / "N halves" style fractions
    def _frac_unit(m: re.Match) -> str:
        word = m.group(1)
        unit = m.group(2)
        if word not in _NUM_WORDS:
            return m.group(0)
        n = _NUM_WORDS[word]
        if n == 1 and unit.endswith("s"):
            unit = unit[:-1]
        return f"{n}/{_FRACTION_UNITS[unit]}"
    t = re.sub(rf"\b(\w+)\s+({'|'.join(sorted(_FRACTION_UNITS, key=len, reverse=True))})\b", _frac_unit, t)
    # hyphenated compound numbers: twenty-five
    for tens in ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]:
        for ones in ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]:
            t = re.sub(rf"\b{tens}-{ones}\b", str(_NUM_WORDS[tens] + _NUM_WORDS[ones]), t)
    # plain word numbers (longest first)
    for w in sorted(_NUM_WORDS, key=len, reverse=True):
        t = re.sub(rf"\b{w}\b", str(_NUM_WORDS[w]), t)
    # "N over M" -> N/M  (only when surrounded by non-word chars)
    t = re.sub(r"\b(\d+(?:/\d+)?)\s+over\s+(\d+(?:/\d+)?)\b", r"\1/\2", t)
    # collapse "2 x" -> "2x"
    t = re.sub(r"(\d)\s+x\b", r"\1x", t)
    t = t.replace("÷", "/").replace("×", "*").replace("−", "-").replace("–", "-")
    t = re.sub(r"\s+", " ", t.strip())
    return t


def _parse_linear(display: str) -> Optional[Tuple[int, int, int]]:
    """Parse '2x + 6 = 14' -> (a, b, c) with b signed."""
    m = re.match(r"^\s*(\d*)x\s*([+-])\s*(\d+)\s*=\s*(\d+)\s*$", display)
    if not m:
        return None
    a = int(m.group(1)) if m.group(1) else 1
    sign = m.group(2)
    b = int(m.group(3)) * (1 if sign == "+" else -1)
    c = int(m.group(4))
    return a, b, c


def _classify_action(
    op: str, operands: List[str], phrase_text: str, problem: Problem, previous_results: List[str]
) -> str:
    """Map a phrase to a canonical action label using problem context."""
    both_sides = bool(re.search(r"both sides|each side", phrase_text))
    linear = None
    if problem.topic == "Algebra" and problem.subtopic == "Linear Equations":
        linear = _parse_linear(problem.display)

    if linear:
        a, b, c = linear
        b_abs = abs(b)
        vals = set(operands)
        try:
            f_vals = {_frac_value(v) for v in vals}
        except Exception:
            f_vals = set()
        if op == "add":
            if b != 0 and {_frac_value(str(b_abs)), _frac_value(str(c))} <= f_vals and len(f_vals) == 2:
                if b > 0:
                    return "added_constant_to_rhs"
                return "added_constant_to_both_sides"
            return "added_values"
        if op == "subtract":
            if (
                b != 0
                and len(f_vals) == 2
                and {_frac_value(str(b_abs)), _frac_value(str(c))} <= f_vals
            ):
                if b > 0 and both_sides:
                    return "subtracted_constant_from_both_sides"
                return "subtracted_constant_from_rhs_only"
            return "subtracted_values"
        if op == "divide":
            divisor = operands[-1] if operands else ""
            if _frac_value(divisor) == _frac_value(str(a)):
                if both_sides:
                    return "divided_both_sides_by_coefficient"
                dividend = operands[0] if len(operands) == 2 else ""
                if dividend and _frac_value(dividend) == _frac_value(str(c)):
                    return "divided_rhs_by_coefficient_only"
                if dividend and dividend in previous_results:
                    return "divided_previous_result_by_coefficient"
                return "divided_by_coefficient"
            return "divided_values"
        if op == "multiply":
            return "multiplied_both_sides_by_coefficient" if both_sides else "multiplied_values"

    if problem.topic == "Fractions" and problem.subtopic == "Adding Fractions" and op == "add":
        return "added_fractions"
    if problem.topic == "Probability" and op == "add":
        return "added_probabilities"
    if problem.topic == "Probability" and op == "divide":
        return "used_favorable_over_total"
    if "order_of_operations" in (problem.concepts or []) and op == "multiply":
        return "evaluated_multiplication_first"
    if "order_of_operations" in (problem.concepts or []) and op == "add":
        return "evaluated_left_to_right"
    return f"{op}_values"


class ReasoningInterpreter:
    """Interprets student speech into structured reasoning."""

    def __init__(self, llm_service=None):
        self.llm = llm_service

    @staticmethod
    def _linear_constants(problem: Problem):
        if problem.topic == "Algebra" and problem.subtopic == "Linear Equations":
            return _parse_linear(problem.display)
        return None

    # ------------------------------------------------------------------
    def interpret(self, problem: Problem, transcript: str) -> StructuredReasoning:
        deterministic = self._interpret_deterministic(problem, transcript)
        if self.llm and self.llm.is_configured:
            try:
                llm_result = self.llm.extract_reasoning(problem, transcript)
                merged = self._merge(problem, transcript, deterministic, llm_result)
                if merged is not None:
                    return merged
            except Exception:
                pass  # deterministic result stands; never crash on LLM failure
        return deterministic

    # ------------------------------------------------------------------
    def from_direct_answer(self, problem: Problem, answer: DirectAnswer) -> StructuredReasoning:
        """Build structured reasoning from a short direct answer.

        The answer is expressed as a single claim that the deterministic
        verifier then evaluates with SymPy — the LLM/parser never decides
        correctness.
        """
        expr = (answer.answer_expression or "").strip()
        variable = answer.answer_variable or ("x" if "x" in (answer.raw_text or "").lower() else None)
        is_equation = problem.topic == "Algebra" and problem.subtopic == "Linear Equations"

        claims: List[MathClaim] = []
        final_answer = expr or None
        actions: List[str] = []

        if expr:
            if variable and is_equation:
                claims.append(MathClaim(
                    text=f"{variable} = {expr}",
                    expression=variable,
                    expected=expr,
                    operation="solve",
                    computed=expr,
                    confidence=0.98,
                ))
                actions = ["solved_equation"]
            else:
                claims.append(MathClaim(
                    text=expr,
                    expression=expr,
                    expected=None,
                    operation="evaluate",
                    computed=expr,
                    confidence=0.98,
                ))
        elif answer.operation:
            # operation-only step response (handled by the step walk, not here)
            actions = [f"{answer.operation}_step"]

        concept = problem.concepts[0] if problem.concepts else problem.subtopic.lower().replace(" ", "_")
        return StructuredReasoning(
            concept=concept,
            student_actions=actions,
            reasoning_pattern=",".join(actions) if actions else "direct_answer",
            mathematical_claims=claims,
            steps=[c.text for c in claims],
            incorrect_steps=[],
            final_answer=final_answer,
            reasoning_quality="sound" if final_answer else "incomplete",
            confidence=max(answer.confidence, 0.9),
            raw_transcript=answer.raw_text,
            source=answer.source,
        )

    # ------------------------------------------------------------------
    def _interpret_deterministic(self, problem: Problem, transcript: str) -> StructuredReasoning:
        text = digitize(transcript)
        claims: List[MathClaim] = []
        actions: List[str] = []
        steps: List[str] = []
        previous_results: List[str] = []
        last_equation: Optional[Tuple[str, str]] = None  # (lhs, rhs) of the most recent equation claim
        final_answer: Optional[str] = None

        # 1. Solve / equation claims first.
        for m in _SOLVE_ANSWER.finditer(text):
            val = m.group(1)
            if final_answer is None:
                final_answer = val
            claims.append(MathClaim(
                text=f"x = {val}", expression="x", expected=val, operation="solve",
                computed=val, confidence=0.9,
            ))
            steps.append(f"x = {val}")
        for m in _SOLVE_X.finditer(text):
            val = m.group(1)
            if final_answer is None:
                final_answer = val
            claims.append(MathClaim(
                text=f"x = {val}", expression="x", expected=val, operation="solve",
                computed=val, confidence=0.9,
            ))
            steps.append(f"x = {val}")
        for m in _EQUATION_WITH_OP.finditer(text):
            op = "-" if ("minus" in m.group(0) or "-" in m.group(0)) and "plus" not in m.group(0) and "+" not in m.group(0) else "+"
            lhs = m.group(1).replace(" ", "") + op + m.group(2)
            rhs = m.group(3)
            claims.append(MathClaim(
                text=f"{lhs} = {rhs}", expression=lhs, expected=rhs, operation="evaluate",
                confidence=0.8,
            ))
            steps.append(f"{lhs} = {rhs}")
            if last_equation is None:
                last_equation = (lhs, rhs)
        for m in _EQUATION_UNLIKE.finditer(text):
            lhs = m.group(1).replace(" ", "") + "+" + m.group(2)
            rhs = m.group(3).replace(" ", "")
            if f"{lhs} = {rhs}" not in [c.text for c in claims]:
                claims.append(MathClaim(
                    text=f"{lhs} = {rhs}", expression=lhs, expected=rhs, operation="evaluate",
                    confidence=0.7,
                ))
                steps.append(f"{lhs} = {rhs}")
        for m in _EQUATION_X_EQ.finditer(text):
            lhs = m.group(1).replace(" ", "")
            rhs = m.group(2)
            if f"{lhs} = {rhs}" not in [c.text for c in claims]:
                claims.append(MathClaim(
                    text=f"{lhs} = {rhs}", expression=lhs, expected=rhs, operation="evaluate",
                    confidence=0.8,
                ))
                steps.append(f"{lhs} = {rhs}")
                if last_equation is None:
                    last_equation = (lhs, rhs)

        # 2. Arithmetic phrases in order of appearance.
        for m in sorted(
            [(op, mm) for op, pat in _PHRASES for mm in pat.finditer(text)],
            key=lambda t: t[1].start(),
        ):
            op, mm = m
            groups = mm.groups()
            if op == "divide" and len(groups) == 1:
                divisor = groups[0]
                dividend = None
                if re.search(r"both sides|each side", mm.group(0)) and last_equation:
                    dividend = last_equation[1]  # use the equation's right-hand side
                elif previous_results:
                    dividend = previous_results[-1]
                operands = [dividend, divisor] if dividend else [divisor]
            elif op == "subtract" and len(groups) == 1:
                # "subtract 6 from both sides": use the equation's RHS constant as the minuend
                operand = groups[0]
                linear = self._linear_constants(problem)
                if linear:
                    operands = [str(linear[2]), operand]
                else:
                    operands = [operand]
            elif op == "subtract" and len(groups) == 2:
                # "subtract X from Y" means Y - X
                operands = [groups[1], groups[0]]
            else:
                operands = [g for g in groups if g is not None]

            # result lookahead
            rest = text[mm.end():mm.end() + 60]
            rm = _RESULT_PATTERN.search(rest)
            result = rm.group(1) if rm else None

            sym_op = _OPERATOR_SYMBOL[op]
            operands_s = [o for o in operands if o]
            expression = f" {sym_op} ".join(operands_s) if operands_s else ""
            if not expression:
                continue

            computed = None
            if len(operands_s) == 2 and all(_frac_value(o) is not None for o in operands_s):
                f1, f2 = _frac_value(operands_s[0]), _frac_value(operands_s[1])
                if op == "add":
                    computed = _render_frac(f1 + f2)
                elif op == "subtract":
                    computed = _render_frac(f1 - f2)
                elif op == "multiply":
                    computed = _render_frac(f1 * f2)
                elif op == "divide":
                    computed = _render_frac(f1 / f2) if f2 != 0 else None
            if computed is not None:
                previous_results.append(computed)

            # Wrong-method phrasing on fraction addition — "by adding numerators
            # and denominators" — states the METHOD without a numeric result.
            # Surface the implied wrong sum (a1+a2)/(b1+b2) as the claim so the
            # misconception detector can catch it like any stated wrong result.
            if (
                result is None
                and op == "add"
                and problem.topic == "Fractions"
                and problem.subtopic == "Adding Fractions"
                and len(operands_s) == 2
                and all(_frac_value(o) is not None for o in operands_s)
                and re.search(r"\bnumerators?\s+and\s+denominators?\b", text)
            ):
                f1, f2 = _frac_value(operands_s[0]), _frac_value(operands_s[1])
                if f1.denominator != 1 or f2.denominator != 1:
                    result = _render_frac(
                        Fraction(f1.numerator + f2.numerator, f1.denominator + f2.denominator)
                    )

            # The student's stated result is their claim — never let our own
            # computation of the expression replace it (that used to turn a
            # stated wrong answer into a "correct" verdict).
            if result:
                final_answer = result
            elif computed is not None:
                final_answer = computed  # provisional; solve claims override below

            if result:
                claim_text = f"{expression} = {result}"
                expected = result
            else:
                claim_text = expression
                expected = None

            action = _classify_action(op, operands_s, mm.group(0), problem, previous_results)
            actions.append(action)
            claim = MathClaim(
                text=claim_text,
                expression=expression,
                expected=expected,
                operation=op,
                computed=computed,
                confidence=0.85,
            )
            claims.append(claim)
            steps.append(claim_text)

        # 3. final answer preference: solve claims win over arithmetic inference.
        solve_claims = [c for c in claims if c.operation == "solve"]
        if solve_claims:
            final_answer = solve_claims[-1].expected
        elif final_answer is None and claims and claims[-1].computed is not None:
            final_answer = claims[-1].computed

        # 4. inconsistent steps (student's stated result != computed result)
        incorrect_steps = []
        for c in claims:
            if c.expected is not None and c.computed is not None and c.expected != c.computed:
                incorrect_steps.append(c.text)

        # 5. quality + confidence
        if not claims and not final_answer:
            quality, confidence = "ambiguous", 0.1
        elif final_answer is None:
            quality, confidence = "incomplete", 0.5
        elif incorrect_steps:
            quality, confidence = "flawed", 0.75
        else:
            quality, confidence = "sound", 0.85
        if actions:
            confidence = min(0.95, confidence + 0.05 * len(actions))

        concept = problem.concepts[0] if problem.concepts else problem.subtopic.lower().replace(" ", "_")
        return StructuredReasoning(
            concept=concept,
            student_actions=actions,
            reasoning_pattern=",".join(actions) if actions else "no_structured_actions",
            mathematical_claims=claims,
            steps=steps,
            incorrect_steps=incorrect_steps,
            final_answer=final_answer,
            reasoning_quality=quality,
            confidence=confidence,
            raw_transcript=transcript,
            source="deterministic",
        )

    # ------------------------------------------------------------------
    def _merge(self, problem, transcript, deterministic, llm_result) -> Optional[StructuredReasoning]:
        """Merge an LLM interpretation with the deterministic one.

        The deterministic extraction is authoritative for claims; the LLM adds
        concept/pattern/actions when present. Returns None when the LLM output
        is unusable.
        """
        if not isinstance(llm_result, dict):
            return None
        det = deterministic.model_dump()
        llm_claims = llm_result.get("mathematical_claims") or []
        claims = det["mathematical_claims"]
        if llm_claims and isinstance(llm_claims, list):
            for lc in llm_claims:
                if not isinstance(lc, dict):
                    continue
                text = lc.get("text") or ""
                if text and text not in [c["text"] for c in claims]:
                    try:
                        claims.append(MathClaim(**{k: v for k, v in lc.items() if k in MathClaim.model_fields}).model_dump())
                    except Exception:
                        pass
        det["mathematical_claims"] = claims
        if llm_result.get("concept"):
            det["concept"] = llm_result["concept"]
        if llm_result.get("reasoning_pattern"):
            det["reasoning_pattern"] = llm_result["reasoning_pattern"]
        if isinstance(llm_result.get("student_actions"), list):
            det["student_actions"] = [a for a in llm_result["student_actions"] if isinstance(a, str)] or det["student_actions"]
        det["source"] = "llm+deterministic"
        return StructuredReasoning(**det)
