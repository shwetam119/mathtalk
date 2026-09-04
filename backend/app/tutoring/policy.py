"""Adaptive tutoring policy.

A separate, deterministic policy layer decides the tutoring strategy. The LLM
is never asked to decide strategy. Inputs:

  current problem, reasoning, verification, misconception, attempt history,
  previous interventions, Qdrant memories, difficulty, mode, progress.

Outputs: intervention type, assistance level, response guidance, next actions.

Memory must change behavior: an active misconception memory that matches the
current diagnosis switches the intervention from generic guidance to a
targeted, memory-referencing intervention.
"""
from __future__ import annotations

from typing import List, Optional

from app.models.schemas import (
    AssistanceLevel,
    Difficulty,
    Intervention,
    InterventionType,
    LearningMode,
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    Misconception,
    Problem,
    StructuredReasoning,
    VerificationResult,
    Verdict,
)


class TutoringPolicy:
    def __init__(self, max_attempts_before_solution: int = 3):
        self.max_attempts_before_solution = max_attempts_before_solution

    # ------------------------------------------------------------------
    def select_intervention(
        self,
        *,
        problem: Problem,
        structured: StructuredReasoning,
        verification: VerificationResult,
        misconception: Misconception,
        attempt_count: int,  # number of reasoning attempts on this problem so far
        hints_used: int,
        previous_intervention: Optional[Intervention],
        retrieved_memories: List[MemoryRecord],
        mode: Optional[LearningMode],
        difficulty: Optional[Difficulty],
    ) -> Intervention:
        """Choose the intervention from deterministic rules."""

        # ---- correct answer -------------------------------------------------
        if verification.verdict == Verdict.CORRECT:
            return Intervention(
                type=InterventionType.PRAISE_AND_NEXT,
                assistance_level=AssistanceLevel.INDEPENDENT,
                message=self._praise_message(problem),
                targeted=False,
                memory_based=False,
                next_actions=["Next problem", "Review", "End session"],
                reason="correct answer with sound reasoning",
                memory_ids_to_resolve=self._memory_ids_to_resolve(retrieved_memories, misconception),
            )

        # ---- correct answer trap (right answer, flawed reasoning) ------------
        if verification.final_answer_correct is True and verification.plan_valid is False:
            return Intervention(
                type=InterventionType.CORRECT_ANSWER_FLAWED_REASONING,
                assistance_level=AssistanceLevel.REVIEW_APPROACH,
                message=self._trap_message(problem, misconception),
                targeted=misconception.detected,
                memory_based=self._has_matching_memory(retrieved_memories, misconception),
                next_actions=["Try again", "Review my approach", "Next problem"],
                reason="correct final answer but flawed reasoning (correct-answer trap)",
            )

        # ---- incorrect ---------------------------------------------------------
        matching_memory = self._matching_memory(retrieved_memories, misconception)

        # explicit request for the full solution or too many failed attempts
        if self._should_show_solution(attempt_count, hints_used):
            return Intervention(
                type=InterventionType.DETAILED_SOLUTION,
                assistance_level=AssistanceLevel.DETAILED_SOLUTION,
                message=self._solution_message(problem),
                targeted=misconception.detected,
                memory_based=matching_memory is not None,
                next_actions=["Next problem", "Review", "End session"],
                reason="repeated failure or explicit request",
            )

        level = self._assistance_level(attempt_count, hints_used, difficulty, mode)

        if matching_memory is not None:
            # ---- MEMORY CHANGES BEHAVIOR ------------------------------------
            return Intervention(
                type=InterventionType.TARGETED_INTERVENTION,
                assistance_level=level,
                message=self._memory_targeted_message(problem, misconception, matching_memory),
                targeted=True,
                memory_based=True,
                next_actions=self._intervention_actions(level),
                reason=(
                    f"retrieved memory '{matching_memory.memory_id}' "
                    f"({matching_memory.metadata.get('misconception_type', '')}) "
                    "matches current diagnosis"
                ),
            )

        if misconception.detected:
            return Intervention(
                type=InterventionType.GENERIC_INTERVENTION,
                assistance_level=level,
                message=self._generic_message(problem),
                targeted=False,
                memory_based=False,
                next_actions=self._intervention_actions(level),
                reason="misconception detected but no matching learner memory",
            )

        return Intervention(
            type=InterventionType.GENERIC_INTERVENTION,
            assistance_level=level,
            message=self._generic_message(problem),
            targeted=False,
            memory_based=False,
            next_actions=self._intervention_actions(level),
            reason="no misconception detected",
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _matching_memory(memories: List[MemoryRecord], misconception: Misconception) -> Optional[MemoryRecord]:
        if not misconception.detected:
            return None
        for m in memories:
            if m.status != MemoryStatus.ACTIVE or m.memory_type != MemoryType.MISCONCEPTION:
                continue
            if m.metadata.get("misconception_type") == misconception.misconception_type:
                return m
            if m.concept == misconception.concept and misconception.misconception_type in str(m.metadata):
                return m
        return None

    @staticmethod
    def _has_matching_memory(memories: List[MemoryRecord], misconception: Misconception) -> bool:
        return TutoringPolicy._matching_memory(memories, misconception) is not None

    @staticmethod
    def _memory_ids_to_resolve(memories: List[MemoryRecord], misconception: Misconception) -> List[str]:
        """When the learner now succeeds, resolve matching active memories."""
        m = TutoringPolicy._matching_memory(memories, misconception)
        return [m.memory_id] if m else []

    @staticmethod
    def _assistance_level(
        attempt_count: int,
        hints_used: int,
        difficulty: Optional[Difficulty],
        mode: Optional[LearningMode],
    ) -> AssistanceLevel:
        if mode == LearningMode.TEST:
            return AssistanceLevel.INDEPENDENT
        # EASY gives slightly earlier support; HARD preserves independence.
        base = 0 if difficulty == Difficulty.HARD else 1
        # attempt 1 -> base (review), attempt 2 -> base+1 (hint), attempt 3 -> base+2 (guided)
        level = base + max(0, attempt_count - 1) + (1 if hints_used > 0 else 0)
        return AssistanceLevel(min(level, AssistanceLevel.GUIDED_EXPLANATION))

    @staticmethod
    def _should_show_solution(attempt_count: int, hints_used: int) -> bool:
        return attempt_count >= 4

    @staticmethod
    def _intervention_actions(level: AssistanceLevel) -> List[str]:
        if level == AssistanceLevel.GUIDED_EXPLANATION:
            return ["Try again", "Show the solution", "End session"]
        return ["Try again", "Hint", "Review my approach", "Show the solution"]

    @staticmethod
    def _praise_message(problem: Problem) -> str:
        return (
            f"Excellent! That is correct — the answer is {problem.expected_answer}. "
            "Your reasoning was clear and the steps were valid."
        )

    @staticmethod
    def _trap_message(problem: Problem, misconception: Misconception) -> str:
        base = (
            f"Your final answer, {problem.expected_answer}, is correct — but the way you "
            "arrived at it is not quite right, and that matters in mathematics."
        )
        if misconception.detected:
            base += f" {misconception.evidence}"
        return base + " Let's make sure the method is sound before moving on."

    @staticmethod
    def _generic_message(problem: Problem) -> str:
        return (
            "Let's work through this together. Try solving the problem step by step, "
            "and check your method as you go. What would you do first?"
        )

    _TYPE_LABELS = {
        "inverse_operation": "inverse operations",
        "equality_manipulation": "keeping the equation balanced",
        "sign_error": "sign errors",
        "combine_unlike_terms": "combining unlike terms",
        "distribution_error": "distribution",
        "fraction_denominator": "fraction denominators",
        "whole_part_confusion": "whole-part confusion",
        "adding_probabilities": "combining probabilities",
        "order_of_operations_error": "order of operations",
        "formula_selection": "formula selection",
        "arithmetic_error": "arithmetic slips",
        "unclear_reasoning": "working through the steps",
    }

    @classmethod
    def _memory_targeted_message(cls, problem: Problem, misconception: Misconception, memory: MemoryRecord) -> str:
        mtype = memory.metadata.get("misconception_type") or misconception.misconception_type
        label = cls._TYPE_LABELS.get(mtype, mtype.replace("_", " "))
        guidance = misconception.recommended_intervention or memory.description
        return (
            f"Earlier, when you practiced {memory.topic or 'mathematics'}, you had trouble "
            f"with {label}. Let's focus on exactly that. {guidance}"
        )

    @staticmethod
    def _solution_message(problem: Problem) -> str:
        from .assistance import detailed_solution

        return detailed_solution(problem)
