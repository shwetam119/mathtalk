"""Adaptive tutoring policy tests.

The critical assertion: WITHOUT memory the policy yields a generic
intervention; WITH a matching learner memory it yields a targeted,
memory-referencing intervention. Memory must change behavior.
"""
from __future__ import annotations

import pytest

from app.mathematics.problems import find_problem
from app.mathematics.verifier import verify
from app.models.schemas import (
    AssistanceLevel,
    Difficulty,
    InterventionType,
    LearningMode,
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    Verdict,
)
from app.reasoning.interpreter import ReasoningInterpreter
from app.reasoning.misconception import MisconceptionDetector
from app.tutoring.policy import TutoringPolicy

interp = ReasoningInterpreter()
detector = MisconceptionDetector()
policy = TutoringPolicy()
p_linear = find_problem("Algebra", "Linear Equations", Difficulty.EASY)

FLAWED = "I add 6 and 14 to get 20 and then divide by 2."
CORRECT = "I subtract 6 from both sides to get 2x equals 8, then divide both sides by 2 to get x equals 4."


def _context(transcript: str):
    sr = interp.interpret(p_linear, transcript)
    vr = verify(sr, p_linear)
    mc = detector.detect(p_linear, sr, vr)
    return sr, vr, mc


def _memory(overrides=None):
    base = dict(
        student_id="student-a",
        concept="linear_equation",
        topic="Algebra",
        memory_type=MemoryType.MISCONCEPTION,
        description="inverse operation guidance",
        evidence="added 6 to 14",
        confidence=0.9,
        metadata={"misconception_type": "inverse_operation"},
    )
    base.update(overrides or {})
    return MemoryRecord(**base)


def test_without_memory_generic_intervention():
    sr, vr, mc = _context(FLAWED)
    iv = policy.select_intervention(
        problem=p_linear, structured=sr, verification=vr, misconception=mc,
        attempt_count=1, hints_used=0, previous_intervention=None,
        retrieved_memories=[], mode=LearningMode.PRACTICE, difficulty=Difficulty.EASY,
    )
    assert iv.type == InterventionType.GENERIC_INTERVENTION
    assert iv.memory_based is False
    assert iv.targeted is False


def test_with_memory_targeted_intervention():
    sr, vr, mc = _context(FLAWED)
    mem = _memory()
    iv = policy.select_intervention(
        problem=p_linear, structured=sr, verification=vr, misconception=mc,
        attempt_count=1, hints_used=0, previous_intervention=None,
        retrieved_memories=[mem], mode=LearningMode.PRACTICE, difficulty=Difficulty.EASY,
    )
    assert iv.type == InterventionType.TARGETED_INTERVENTION
    assert iv.memory_based is True
    assert iv.targeted is True
    assert "earlier" in iv.message.lower() or "before" in iv.message.lower()
    assert "inverse" in iv.message.lower()
    assert "undo" in iv.message.lower()


def test_memory_must_change_behavior():
    """The two interventions must actually differ."""
    sr, vr, mc = _context(FLAWED)
    no_mem = policy.select_intervention(
        problem=p_linear, structured=sr, verification=vr, misconception=mc,
        attempt_count=1, hints_used=0, previous_intervention=None,
        retrieved_memories=[], mode=LearningMode.PRACTICE, difficulty=Difficulty.EASY,
    )
    with_mem = policy.select_intervention(
        problem=p_linear, structured=sr, verification=vr, misconception=mc,
        attempt_count=1, hints_used=0, previous_intervention=None,
        retrieved_memories=[_memory()], mode=LearningMode.PRACTICE, difficulty=Difficulty.EASY,
    )
    assert no_mem.message != with_mem.message
    assert no_mem.memory_based != with_mem.memory_based
    assert no_mem.type != with_mem.type


def test_resolved_memory_does_not_trigger_targeting():
    sr, vr, mc = _context(FLAWED)
    mem = _memory({"status": MemoryStatus.RESOLVED})
    iv = policy.select_intervention(
        problem=p_linear, structured=sr, verification=vr, misconception=mc,
        attempt_count=1, hints_used=0, previous_intervention=None,
        retrieved_memories=[mem], mode=LearningMode.PRACTICE, difficulty=Difficulty.EASY,
    )
    assert iv.memory_based is False


def test_correct_answer_praise():
    sr, vr, mc = _context(CORRECT)
    iv = policy.select_intervention(
        problem=p_linear, structured=sr, verification=vr, misconception=mc,
        attempt_count=1, hints_used=0, previous_intervention=None,
        retrieved_memories=[], mode=LearningMode.PRACTICE, difficulty=Difficulty.EASY,
    )
    assert iv.type == InterventionType.PRAISE_AND_NEXT
    assert iv.assistance_level == AssistanceLevel.INDEPENDENT


def test_correct_answer_trap_intervention():
    sr, vr, mc = _context("I subtract 6 from 14 to get 8, then divide 8 by 2 to get 4.")
    assert vr.verdict == Verdict.INCORRECT and vr.final_answer_correct is True
    iv = policy.select_intervention(
        problem=p_linear, structured=sr, verification=vr, misconception=mc,
        attempt_count=1, hints_used=0, previous_intervention=None,
        retrieved_memories=[], mode=LearningMode.PRACTICE, difficulty=Difficulty.EASY,
    )
    assert iv.type == InterventionType.CORRECT_ANSWER_FLAWED_REASONING


def test_escalation_on_repeated_failure():
    sr, vr, mc = _context(FLAWED)
    levels = []
    for attempt in range(1, 4):
        iv = policy.select_intervention(
            problem=p_linear, structured=sr, verification=vr, misconception=mc,
            attempt_count=attempt, hints_used=0, previous_intervention=None,
            retrieved_memories=[], mode=LearningMode.PRACTICE, difficulty=Difficulty.EASY,
        )
        levels.append(iv.assistance_level)
    assert levels[0] < levels[1] <= levels[2]


def test_test_mode_withholds_help():
    sr, vr, mc = _context(FLAWED)
    iv = policy.select_intervention(
        problem=p_linear, structured=sr, verification=vr, misconception=mc,
        attempt_count=3, hints_used=0, previous_intervention=None,
        retrieved_memories=[], mode=LearningMode.TEST, difficulty=Difficulty.EASY,
    )
    assert iv.assistance_level == AssistanceLevel.INDEPENDENT


def test_solution_after_too_many_attempts():
    sr, vr, mc = _context(FLAWED)
    iv = policy.select_intervention(
        problem=p_linear, structured=sr, verification=vr, misconception=mc,
        attempt_count=5, hints_used=0, previous_intervention=None,
        retrieved_memories=[], mode=LearningMode.PRACTICE, difficulty=Difficulty.EASY,
    )
    assert iv.type == InterventionType.DETAILED_SOLUTION
    assert iv.assistance_level == AssistanceLevel.DETAILED_SOLUTION
