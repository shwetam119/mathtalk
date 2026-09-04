"""Progressive assistance.

LEVEL 0  Independent attempt
LEVEL 1  Review my approach
LEVEL 2  Hint
LEVEL 3  Guided explanation
LEVEL 4  Detailed solution

Escalation is driven by demonstrated need (incorrect reasoning, repeated
failures, explicit requests, previous interventions, learner memory) — never
by revealing the full solution too early.
"""
from __future__ import annotations

from typing import List, Optional

from app.models.schemas import AssistanceLevel, Misconception, Problem

LEVEL_LABELS = {
    AssistanceLevel.INDEPENDENT: "Independent attempt",
    AssistanceLevel.REVIEW_APPROACH: "Review my approach",
    AssistanceLevel.HINT: "Hint",
    AssistanceLevel.GUIDED_EXPLANATION: "Guided explanation",
    AssistanceLevel.DETAILED_SOLUTION: "Detailed solution",
}

# concept -> short directional hints (generic, misconception-independent)
_CONCEPT_HINTS = {
    "linear_equation": "In an equation, what you do to one side you must do to the other. "
                      "What is the very first thing you can do to get the variable alone?",
    "inverse_operations": "Think about the inverse: addition is undone by subtraction, "
                          "multiplication by division.",
    "equality": "Keep the equation balanced: any operation must be applied to both sides.",
    "adding_fractions": "You can only add fractions when their denominators match. "
                        "How can you rewrite them with a common denominator?",
    "equivalent_fractions": "To change a fraction's form, multiply or divide the top and "
                            "bottom by the same number.",
    "probability": "Probability is the number of favorable outcomes divided by the total "
                   "number of outcomes.",
    "order_of_operations": "Multiplication and division come before addition and subtraction.",
    "distribution": "Multiply the outside number by every term inside the bracket.",
    "like_terms": "Only terms with the same variable part can be combined.",
    "combining_terms": "Only terms with the same variable part can be combined.",
}


def level_label(level: AssistanceLevel) -> str:
    return LEVEL_LABELS.get(level, "Independent attempt")


def generic_hint(problem: Problem) -> str:
    for concept in problem.concepts or []:
        if concept in _CONCEPT_HINTS:
            return _CONCEPT_HINTS[concept]
    return "Break the problem into smaller steps and check each one."


def guided_explanation(problem: Problem) -> str:
    """More explicit, but still leaves the next computation to the student."""
    steps = problem.solution_steps
    if not steps:
        return generic_hint(problem)
    if len(steps) == 1:
        return f"Here is the idea: {steps[0]}. Now you try the calculation."
    return (
        f"Let's work through it together. Step 1: {steps[0]}. "
        "What should you do next to finish? Try it from here."
    )


def detailed_solution(problem: Problem) -> str:
    """Complete, mathematically verified, step-by-step solution in short chunks."""
    steps = problem.solution_steps
    body = " ".join(f"{i + 1}. {s}" for i, s in enumerate(steps))
    return f"Here is the full solution. {body} The answer is {problem.expected_answer}."


def review_approach(problem: Problem, misconception: Optional[Misconception]) -> str:
    """Level-1 review: reflect the student's own approach back at them."""
    if misconception and misconception.detected:
        return (
            f"Let's review your approach. {misconception.evidence} "
            f"Here is a question to think about: {misconception.recommended_intervention}"
        )
    return (
        f"Let's review your approach to this problem. What was your first step, "
        f"and why did you choose it? Start again when you are ready."
    )
