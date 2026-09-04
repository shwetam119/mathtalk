"""Structured mathematics problem engine.

Every problem carries deterministic metadata: expected answer (SymPy-parseable),
solution steps, concepts and common misconceptions. The tutoring engine and the
verifier rely on this metadata; nothing is hardcoded around a single example.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import re

from app.models.schemas import Difficulty, Problem, TutoringStep

# topic -> subtopics
TOPICS: Dict[str, List[str]] = {
    "Arithmetic": ["Addition and Subtraction", "Multiplication and Division", "Order of Operations"],
    "Algebra": ["Linear Equations", "Simplifying Expressions"],
    "Fractions": ["Equivalent Fractions", "Adding Fractions"],
    "Probability": ["Basic Probability", "Compound Events"],
}

_PROBLEMS: List[Problem] = [
    # ------------------------------------------------------------------ arithmetic
    Problem(
        problem_id="ar-add-01",
        topic="Arithmetic",
        subtopic="Addition and Subtraction",
        difficulty=Difficulty.EASY,
        prompt="What is 47 plus 38?",
        display="47 + 38 = ?",
        expected_answer="85",
        answer_expr="85",
        solution_steps=["Add the tens: 40 plus 30 is 70.", "Add the ones: 7 plus 8 is 15.", "70 plus 15 is 85."],
        concepts=["addition", "place_value"],
        common_misconceptions=["carry_error", "place_value_error"],
    ),
    Problem(
        problem_id="ar-add-02",
        topic="Arithmetic",
        subtopic="Addition and Subtraction",
        difficulty=Difficulty.EASY,
        prompt="What is 102 minus 57?",
        display="102 − 57 = ?",
        expected_answer="45",
        answer_expr="45",
        solution_steps=["Borrow 1 from the tens: 12 minus 7 is 5.", "Tens: 9 minus 5 is 4.", "Answer is 45."],
        concepts=["subtraction", "borrowing"],
        common_misconceptions=["sign_error", "borrowing_error"],
    ),
    Problem(
        problem_id="ar-mul-01",
        topic="Arithmetic",
        subtopic="Multiplication and Division",
        difficulty=Difficulty.EASY,
        prompt="What is 7 times 8?",
        display="7 × 8 = ?",
        expected_answer="56",
        answer_expr="56",
        solution_steps=["7 times 8 is 56."],
        concepts=["multiplication", "times_tables"],
        common_misconceptions=["times_table_error"],
    ),
    Problem(
        problem_id="ar-div-01",
        topic="Arithmetic",
        subtopic="Multiplication and Division",
        difficulty=Difficulty.MEDIUM,
        prompt="What is 144 divided by 12?",
        display="144 ÷ 12 = ?",
        expected_answer="12",
        answer_expr="12",
        solution_steps=["12 times 12 is 144, so 144 divided by 12 is 12."],
        concepts=["division", "multiplication_facts"],
        common_misconceptions=["inverse_operation", "division_error"],
    ),
    Problem(
        problem_id="ar-oop-01",
        topic="Arithmetic",
        subtopic="Order of Operations",
        difficulty=Difficulty.MEDIUM,
        prompt="Evaluate 2 plus 3 times 4.",
        display="2 + 3 × 4 = ?",
        expected_answer="14",
        answer_expr="14",
        solution_steps=["Multiplication comes before addition.", "3 times 4 is 12.", "2 plus 12 is 14."],
        concepts=["order_of_operations", "multiplication"],
        common_misconceptions=["left_to_right_error", "order_of_operations_error"],
    ),
    Problem(
        problem_id="ar-oop-02",
        topic="Arithmetic",
        subtopic="Order of Operations",
        difficulty=Difficulty.HARD,
        prompt="Evaluate 10 minus 2 times 3.",
        display="10 − 2 × 3 = ?",
        expected_answer="4",
        answer_expr="4",
        solution_steps=["Multiplication comes before subtraction.", "2 times 3 is 6.", "10 minus 6 is 4."],
        concepts=["order_of_operations", "subtraction"],
        common_misconceptions=["left_to_right_error", "sign_error"],
    ),
    # ------------------------------------------------------------------ algebra
    Problem(
        problem_id="alg-le-01",
        topic="Algebra",
        subtopic="Linear Equations",
        difficulty=Difficulty.EASY,
        prompt="Solve for x. Two x plus 6 equals 14.",
        display="2x + 6 = 14",
        expected_answer="4",
        answer_expr="4",
        solution_steps=[
            "Subtract 6 from both sides: 2x = 8.",
            "Divide both sides by 2: x = 4.",
        ],
        concepts=["linear_equation", "inverse_operations", "equality"],
        common_misconceptions=["inverse_operation", "equality_manipulation", "sign_error"],
    ),
    Problem(
        problem_id="alg-le-02",
        topic="Algebra",
        subtopic="Linear Equations",
        difficulty=Difficulty.EASY,
        prompt="Solve for x. Three x plus 4 equals 19.",
        display="3x + 4 = 19",
        expected_answer="5",
        answer_expr="5",
        solution_steps=[
            "Subtract 4 from both sides: 3x = 15.",
            "Divide both sides by 3: x = 5.",
        ],
        concepts=["linear_equation", "inverse_operations", "equality"],
        common_misconceptions=["inverse_operation", "equality_manipulation"],
    ),
    Problem(
        problem_id="alg-le-03",
        topic="Algebra",
        subtopic="Linear Equations",
        difficulty=Difficulty.MEDIUM,
        prompt="Solve for x. Two x minus 6 equals 10.",
        display="2x − 6 = 10",
        expected_answer="8",
        answer_expr="8",
        solution_steps=[
            "Add 6 to both sides: 2x = 16.",
            "Divide both sides by 2: x = 8.",
        ],
        concepts=["linear_equation", "inverse_operations", "equality"],
        common_misconceptions=["inverse_operation", "equality_manipulation", "sign_error"],
    ),
    Problem(
        problem_id="alg-le-04",
        topic="Algebra",
        subtopic="Linear Equations",
        difficulty=Difficulty.MEDIUM,
        prompt="Solve for x. Five x plus 2 equals 17.",
        display="5x + 2 = 17",
        expected_answer="3",
        answer_expr="3",
        solution_steps=[
            "Subtract 2 from both sides: 5x = 15.",
            "Divide both sides by 5: x = 3.",
        ],
        concepts=["linear_equation", "inverse_operations", "equality"],
        common_misconceptions=["inverse_operation", "equality_manipulation"],
    ),
    Problem(
        problem_id="alg-le-05",
        topic="Algebra",
        subtopic="Linear Equations",
        difficulty=Difficulty.HARD,
        prompt="Solve for x. Four x plus 7 equals 31.",
        display="4x + 7 = 31",
        expected_answer="6",
        answer_expr="6",
        solution_steps=[
            "Subtract 7 from both sides: 4x = 24.",
            "Divide both sides by 4: x = 6.",
        ],
        concepts=["linear_equation", "inverse_operations", "equality"],
        common_misconceptions=["inverse_operation", "equality_manipulation"],
    ),
    Problem(
        problem_id="alg-simp-01",
        topic="Algebra",
        subtopic="Simplifying Expressions",
        difficulty=Difficulty.EASY,
        prompt="Simplify three x plus two x.",
        display="3x + 2x = ?",
        expected_answer="5x",
        answer_expr="5*x",
        solution_steps=["Both terms have the variable x.", "3 plus 2 is 5, so the result is 5x."],
        concepts=["like_terms", "combining_terms"],
        common_misconceptions=["combine_unlike_terms", "sign_error"],
    ),
    Problem(
        problem_id="alg-simp-02",
        topic="Algebra",
        subtopic="Simplifying Expressions",
        difficulty=Difficulty.MEDIUM,
        prompt="Expand two times the quantity x plus 3.",
        display="2(x + 3) = ?",
        expected_answer="2x + 6",
        answer_expr="2*x + 6",
        solution_steps=["Use the distributive property.", "2 times x is 2x.", "2 times 3 is 6. Result: 2x + 6."],
        concepts=["distribution", "expanding"],
        common_misconceptions=["distribution_error", "combine_unlike_terms"],
    ),
    # ------------------------------------------------------------------ fractions
    Problem(
        problem_id="frac-eq-01",
        topic="Fractions",
        subtopic="Equivalent Fractions",
        difficulty=Difficulty.EASY,
        prompt="One half equals how many eighths?",
        display="1/2 = ?/8",
        expected_answer="4/8",
        answer_expr="4/8",
        solution_steps=["Multiply top and bottom by 4.", "1 times 4 is 4, 2 times 4 is 8.", "So 1/2 = 4/8."],
        concepts=["equivalent_fractions", "scaling"],
        common_misconceptions=["whole_part_confusion", "fraction_denominator"],
    ),
    Problem(
        problem_id="frac-eq-02",
        topic="Fractions",
        subtopic="Equivalent Fractions",
        difficulty=Difficulty.MEDIUM,
        prompt="Simplify six eighths.",
        display="6/8 = ?",
        expected_answer="3/4",
        answer_expr="3/4",
        solution_steps=["Divide top and bottom by 2.", "6 divided by 2 is 3, 8 divided by 2 is 4.", "So 6/8 = 3/4."],
        concepts=["simplifying_fractions", "greatest_common_factor"],
        common_misconceptions=["fraction_denominator", "whole_part_confusion"],
    ),
    Problem(
        problem_id="frac-add-01",
        topic="Fractions",
        subtopic="Adding Fractions",
        difficulty=Difficulty.EASY,
        prompt="What is one half plus one quarter?",
        display="1/2 + 1/4 = ?",
        expected_answer="3/4",
        answer_expr="3/4",
        solution_steps=["The common denominator is 4.", "1/2 = 2/4.", "2/4 + 1/4 = 3/4."],
        concepts=["adding_fractions", "common_denominator"],
        common_misconceptions=["fraction_denominator", "adding_numerators_only"],
    ),
    Problem(
        problem_id="frac-add-02",
        topic="Fractions",
        subtopic="Adding Fractions",
        difficulty=Difficulty.MEDIUM,
        prompt="What is two thirds plus one sixth?",
        display="2/3 + 1/6 = ?",
        expected_answer="5/6",
        answer_expr="5/6",
        solution_steps=["The common denominator is 6.", "2/3 = 4/6.", "4/6 + 1/6 = 5/6."],
        concepts=["adding_fractions", "common_denominator"],
        common_misconceptions=["fraction_denominator", "adding_numerators_only"],
    ),
    Problem(
        problem_id="frac-add-03",
        topic="Fractions",
        subtopic="Adding Fractions",
        difficulty=Difficulty.EASY,
        prompt="What is one third plus one quarter?",
        display="1/3 + 1/4 = ?",
        expected_answer="7/12",
        answer_expr="7/12",
        solution_steps=["The common denominator is 12.", "1/3 = 4/12.", "1/4 = 3/12.", "4/12 + 3/12 = 7/12."],
        concepts=["adding_fractions", "common_denominator"],
        common_misconceptions=["fraction_denominator", "adding_numerators_only"],
    ),
    # ------------------------------------------------------------------ probability
    Problem(
        problem_id="prob-basic-01",
        topic="Probability",
        subtopic="Basic Probability",
        difficulty=Difficulty.EASY,
        prompt="A bag has 3 red marbles and 5 blue marbles. What is the probability of picking a red marble?",
        display="P(red) = ?",
        expected_answer="3/8",
        answer_expr="3/8",
        solution_steps=["Total marbles: 3 plus 5 is 8.", "Favorable outcomes: 3 red marbles.", "Probability is 3 out of 8, or 3 eighths."],
        concepts=["probability", "favorable_over_total"],
        common_misconceptions=["whole_part_confusion", "favorable_over_total"],
    ),
    Problem(
        problem_id="prob-basic-02",
        topic="Probability",
        subtopic="Basic Probability",
        difficulty=Difficulty.EASY,
        prompt="When rolling a fair six-sided die, what is the probability of rolling an even number?",
        display="P(even) = ?",
        expected_answer="1/2",
        answer_expr="1/2",
        solution_steps=["Even numbers on a die: 2, 4, 6 — that is 3 outcomes.", "Total outcomes: 6.", "Probability is 3 out of 6, which simplifies to one half."],
        concepts=["probability", "favorable_over_total"],
        common_misconceptions=["whole_part_confusion", "counting_error"],
    ),
    Problem(
        problem_id="prob-comp-01",
        topic="Probability",
        subtopic="Compound Events",
        difficulty=Difficulty.MEDIUM,
        prompt="You flip a fair coin twice. What is the probability of getting two heads?",
        display="P(HH) = ?",
        expected_answer="1/4",
        answer_expr="1/4",
        solution_steps=["Each flip has 2 outcomes, so there are 4 total outcomes.", "Only 1 outcome is two heads.", "Probability is 1 out of 4, or one quarter."],
        concepts=["compound_events", "multiplication_rule"],
        common_misconceptions=["adding_probabilities", "sample_space_error"],
    ),
    Problem(
        problem_id="prob-comp-02",
        topic="Probability",
        subtopic="Compound Events",
        difficulty=Difficulty.MEDIUM,
        prompt="You roll a die and flip a coin. What is the probability of rolling a 6 and getting heads?",
        display="P(6 and H) = ?",
        expected_answer="1/12",
        answer_expr="1/12",
        solution_steps=["Die: 6 outcomes. Coin: 2 outcomes. Total: 12.", "Only 1 favorable outcome.", "Probability is 1 out of 12."],
        concepts=["compound_events", "multiplication_rule"],
        common_misconceptions=["adding_probabilities", "sample_space_error"],
    ),
]

PROBLEMS_BY_ID: Dict[str, Problem] = {p.problem_id: p for p in _PROBLEMS}


# ---------------------------------------------------------------------------
# Guided tutoring steps (smallest-useful-intervention walkthrough)
# ---------------------------------------------------------------------------
def _linear_steps(problem: Problem) -> List["TutoringStep"]:
    """Step walk for ax + b = c: undo constant, read result, undo coefficient, answer."""
    m = re.match(r"^\s*(\d*)x\s*([+-])\s*(\d+)\s*=\s*(\d+)\s*$", problem.display)
    if not m:
        return []
    a = int(m.group(1)) if m.group(1) else 1
    sign = m.group(2)
    b = int(m.group(3)) * (1 if sign == "+" else -1)
    c = int(m.group(4))
    mid = c - b
    steps: List["TutoringStep"] = []
    if b > 0:
        steps.append(TutoringStep(
            step_id=f"{problem.problem_id}-s1",
            question=f"Not quite. Let's check the first step. What should we do with the {b}?",
            expected_op="subtract",
            op_accept=["minus", "take away"],
            hint=f"Think about the opposite of adding {b}: what operation would undo it on both sides?",
            confirm="Exactly.",
        ))
        hint_mid = f"Subtract {b} from both sides of {problem.display}."
    else:
        steps.append(TutoringStep(
            step_id=f"{problem.problem_id}-s1",
            question=f"Not quite. Let's check the first step. What should we do with the {abs(b)}?",
            expected_op="add",
            op_accept=["plus"],
            hint=f"Think about the opposite of subtracting {abs(b)}: what operation would undo it on both sides?",
            confirm="Exactly.",
        ))
        hint_mid = f"Add {abs(b)} to both sides of {problem.display}."
    if a > 1:
        steps.append(TutoringStep(
            step_id=f"{problem.problem_id}-s2",
            question="What does that leave us with?",
            expected_expr=f"{a}x = {mid}",
            hint=hint_mid,
            confirm="Good.",
        ))
        steps.append(TutoringStep(
            step_id=f"{problem.problem_id}-s3",
            question=f"Now what should we do with the {a}?",
            expected_op="divide",
            op_accept=["division", "dividing"],
            hint=f"The {a} multiplies x, so undo it by dividing both sides by {a}.",
            confirm="Exactly.",
        ))
        steps.append(TutoringStep(
            step_id=f"{problem.problem_id}-s4",
            question="So what is x?",
            expected_expr=str(mid // a) if mid % a == 0 else f"{mid}/{a}",
            hint=f"{mid} divided by {a} is {mid // a if mid % a == 0 else f'{mid}/{a}'}.",
            confirm="Correct! Well done.",
        ))
    else:
        steps.append(TutoringStep(
            step_id=f"{problem.problem_id}-s2",
            question="What does that leave us with?",
            expected_expr=str(mid),
            hint=hint_mid,
            confirm="Correct! Well done.",
        ))
    return steps


def _order_of_ops_steps(problem: Problem) -> List["TutoringStep"]:
    """Step walk for 'a op1 b × c' style expressions (one higher-precedence op)."""
    m = re.match(r"^\s*(\d+)\s*([+−-])\s*(\d+)\s*[×*]\s*(\d+)\s*$", problem.display)
    if not m:
        return []
    a, op1, b, c = int(m.group(1)), m.group(2), int(m.group(3)), int(m.group(4))
    product = b * c
    final = a + product if op1 == "+" else a - product
    return [
        TutoringStep(
            step_id=f"{problem.problem_id}-s1",
            question="Not quite. Which operation should we do first?",
            expected_op="multiply",
            op_accept=["multiplication", "times"],
            hint="Multiplication and division come before addition and subtraction.",
            confirm="Exactly.",
        ),
        TutoringStep(
            step_id=f"{problem.problem_id}-s2",
            question=f"What is {b} times {c}?",
            expected_expr=str(product),
            hint=f"{b} times {c} is {product}.",
            confirm="Good.",
        ),
        TutoringStep(
            step_id=f"{problem.problem_id}-s3",
            question=f"So what is {a} {'plus' if op1 == '+' else 'minus'} {product}?",
            expected_expr=str(final),
            hint=f"{a} {'plus' if op1 == '+' else 'minus'} {product} is {final}.",
            confirm="Correct! Well done.",
        ),
    ]


def _fraction_steps(problem: Problem) -> List["TutoringStep"]:
    """Step walks for the fraction problems."""
    pid = problem.problem_id
    if pid == "frac-add-01":  # 1/2 + 1/4 = ?
        return [
            TutoringStep(
                step_id=f"{pid}-s1",
                question="Not quite. What is one half written with a denominator of 4?",
                expected_expr="2/4",
                hint="Multiply the top and bottom of 1/2 by 2.",
                confirm="Good.",
            ),
            TutoringStep(
                step_id=f"{pid}-s2",
                question="Now what is 2/4 plus 1/4?",
                expected_expr="3/4",
                hint="Add the numerators; the denominator stays 4.",
                confirm="Correct! Well done.",
            ),
        ]
    if pid == "frac-add-02":  # 2/3 + 1/6 = ?
        return [
            TutoringStep(
                step_id=f"{pid}-s1",
                question="Not quite. What is two thirds written with a denominator of 6?",
                expected_expr="4/6",
                hint="Multiply the top and bottom of 2/3 by 2.",
                confirm="Good.",
            ),
            TutoringStep(
                step_id=f"{pid}-s2",
                question="Now what is 4/6 plus 1/6?",
                expected_expr="5/6",
                hint="Add the numerators; the denominator stays 6.",
                confirm="Correct! Well done.",
            ),
        ]
    if pid == "frac-add-03":  # 1/3 + 1/4 = ?
        return [
            TutoringStep(
                step_id=f"{pid}-s1",
                question="Not quite. What is one third written with a denominator of 12?",
                expected_expr="4/12",
                hint="Multiply the top and bottom of 1/3 by 4.",
                confirm="Good.",
            ),
            TutoringStep(
                step_id=f"{pid}-s2",
                question="Now what is 4/12 plus 3/12?",
                expected_expr="7/12",
                hint="Add the numerators; the denominator stays 12.",
                confirm="Correct! Well done.",
            ),
        ]
    if pid == "frac-eq-01":  # 1/2 = ?/8
        return [
            TutoringStep(
                step_id=f"{pid}-s1",
                question="Not quite. How do we change the denominator from 2 to 8?",
                expected_op="multiply",
                op_accept=["multiplication", "times"],
                hint="Multiply the top and bottom by the same number. 2 times what is 8?",
                confirm="Good.",
            ),
            TutoringStep(
                step_id=f"{pid}-s2",
                question="So what is one half written with a denominator of 8?",
                expected_expr="4/8",
                hint="1 times 4 is 4, and 2 times 4 is 8.",
                confirm="Correct! Well done.",
            ),
        ]
    if pid == "frac-eq-02":  # simplify 6/8
        return [
            TutoringStep(
                step_id=f"{pid}-s1",
                question="Not quite. What number divides both 6 and 8 evenly?",
                expected_expr="2",
                hint="What is the largest number that goes into both 6 and 8?",
                confirm="Good.",
            ),
            TutoringStep(
                step_id=f"{pid}-s2",
                question="So what is 6/8 simplified?",
                expected_expr="3/4",
                hint="Divide the top and bottom by 2.",
                confirm="Correct! Well done.",
            ),
        ]
    return []


def _probability_steps(problem: Problem) -> List["TutoringStep"]:
    pid = problem.problem_id
    if pid == "prob-basic-01":  # 3 red, 5 blue -> P(red)
        return [
            TutoringStep(
                step_id=f"{pid}-s1",
                question="Not quite. How many marbles are there in total?",
                expected_expr="8",
                hint="Add the red and blue marbles together.",
                confirm="Good.",
            ),
            TutoringStep(
                step_id=f"{pid}-s2",
                question="So what is the probability of picking a red marble?",
                expected_expr="3/8",
                hint="Favorable outcomes (3 red) divided by total outcomes (8).",
                confirm="Correct! Well done.",
            ),
        ]
    if pid == "prob-basic-02":  # die even
        return [
            TutoringStep(
                step_id=f"{pid}-s1",
                question="Not quite. How many even numbers are there on a die?",
                expected_expr="3",
                hint="The even numbers on a die are 2, 4 and 6.",
                confirm="Good.",
            ),
            TutoringStep(
                step_id=f"{pid}-s2",
                question="So what is the probability of rolling an even number?",
                expected_expr="1/2",
                hint="3 favorable outcomes out of 6 total outcomes.",
                confirm="Correct! Well done.",
            ),
        ]
    if pid == "prob-comp-01":  # two heads
        return [
            TutoringStep(
                step_id=f"{pid}-s1",
                question="Not quite. How many outcomes are there when you flip a coin twice?",
                expected_expr="4",
                hint="Each flip has 2 outcomes, so 2 times 2.",
                confirm="Good.",
            ),
            TutoringStep(
                step_id=f"{pid}-s2",
                question="So what is the probability of two heads?",
                expected_expr="1/4",
                hint="Only 1 of the 4 outcomes is two heads.",
                confirm="Correct! Well done.",
            ),
        ]
    if pid == "prob-comp-02":  # die + coin
        return [
            TutoringStep(
                step_id=f"{pid}-s1",
                question="Not quite. How many total outcomes are there?",
                expected_expr="12",
                hint="The die has 6 outcomes and the coin has 2: 6 times 2.",
                confirm="Good.",
            ),
            TutoringStep(
                step_id=f"{pid}-s2",
                question="So what is the probability of a 6 and heads?",
                expected_expr="1/12",
                hint="Only 1 favorable outcome out of 12.",
                confirm="Correct! Well done.",
            ),
        ]
    return []


def _attach_tutoring_steps() -> None:
    """Attach guided step walks to problems that support them."""
    for p in _PROBLEMS:
        if p.topic == "Algebra" and p.subtopic == "Linear Equations":
            p.tutoring_steps = _linear_steps(p)
            p.ask_question = "What is x?"
        elif p.topic == "Arithmetic" and p.subtopic == "Order of Operations":
            p.tutoring_steps = _order_of_ops_steps(p)
        elif p.topic == "Fractions":
            p.tutoring_steps = _fraction_steps(p)
        elif p.topic == "Probability":
            p.tutoring_steps = _probability_steps(p)


_attach_tutoring_steps()


def list_topics() -> List[str]:
    return list(TOPICS.keys())


def list_subtopics(topic: str) -> List[str]:
    return TOPICS.get(topic, [])


def available_difficulties() -> List[str]:
    return [d.value for d in Difficulty]


def find_problem(topic: str, subtopic: str, difficulty: Difficulty, exclude: Optional[List[str]] = None) -> Optional[Problem]:
    """Pick a problem for the selection; prefer un-attempted ones."""
    exclude = exclude or []
    pool = [
        p for p in _PROBLEMS
        if p.topic == topic and p.subtopic == subtopic and p.difficulty == difficulty and p.problem_id not in exclude
    ]
    if not pool:
        pool = [p for p in _PROBLEMS if p.topic == topic and p.subtopic == subtopic and p.problem_id not in exclude]
    if not pool:
        pool = [p for p in _PROBLEMS if p.topic == topic and p.subtopic == subtopic]
    if not pool:
        return None
    # deterministic: lowest id first (keeps demos and tests reproducible)
    return sorted(pool, key=lambda p: p.problem_id)[0]


def related_problem(problem: Problem, exclude: Optional[List[str]] = None) -> Optional[Problem]:
    """A related problem in the same topic/subtopic (different id)."""
    exclude = set(exclude or [])
    exclude.add(problem.problem_id)
    pool = [p for p in _PROBLEMS if p.topic == problem.topic and p.subtopic == problem.subtopic and p.problem_id not in exclude]
    if not pool:
        pool = [p for p in _PROBLEMS if p.topic == problem.topic and p.problem_id not in exclude]
    return sorted(pool, key=lambda p: p.problem_id)[0] if pool else None
