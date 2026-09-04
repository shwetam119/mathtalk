"""Spoken-mathematics normalization and direct-answer extraction tests."""
from __future__ import annotations

from app.mathematics.spoken import extract_direct_answer, match_operation, normalize_spoken_math, words_to_int


def test_words_to_int():
    assert words_to_int(["four"]) == 4
    assert words_to_int(["twenty", "five"]) == 25
    assert words_to_int(["two", "hundred"]) == 200
    assert words_to_int(["banana"]) is None


def test_normalize_numbers():
    assert normalize_spoken_math("four") == "4"
    assert normalize_spoken_math("seven") == "7"
    assert normalize_spoken_math("zero") == "0"
    assert normalize_spoken_math("fifty six") == "56"


def test_normalize_negative():
    assert normalize_spoken_math("negative five") == "-5"
    assert normalize_spoken_math("minus five") == "-5"


def test_normalize_fractions():
    assert normalize_spoken_math("three quarters") == "3/4"
    assert normalize_spoken_math("three-fourths") == "3/4"
    assert normalize_spoken_math("one half") == "1/2"
    assert normalize_spoken_math("quarter") == "1/4"
    assert normalize_spoken_math("three eighths") == "3/8"


def test_normalize_decimal_and_percent():
    assert normalize_spoken_math("two point five") == "2.5"
    assert normalize_spoken_math("twenty five percent") == "25/100"


def test_normalize_variables():
    assert normalize_spoken_math("x equals four") == "x = 4"
    assert normalize_spoken_math("x is 4") == "x = 4"
    assert normalize_spoken_math("two x plus four") == "2x + 4"
    assert normalize_spoken_math("three x minus two") == "3x - 2"
    assert normalize_spoken_math("2x equals 8") == "2x = 8"


def test_extract_plain_numbers():
    for t in ("4", "56", "eight", "zero", "8"):
        da = extract_direct_answer(t)
        assert da is not None, t
        assert da.answer_expression.isdigit(), t


def test_extract_negative_and_fraction():
    assert extract_direct_answer("negative five").answer_expression == "-5"
    assert extract_direct_answer("three quarters").answer_expression == "3/4"
    assert extract_direct_answer("three-fourths").answer_expression == "3/4"
    assert extract_direct_answer("quarter").answer_expression == "1/4"


def test_extract_phrase_answers():
    assert extract_direct_answer("the answer is four").answer_expression == "4"
    assert extract_direct_answer("I got 4").answer_expression == "4"
    assert extract_direct_answer("I think it's 4").answer_expression == "4"
    assert extract_direct_answer("it's 56").answer_expression == "56"


def test_extract_variable_answer():
    da = extract_direct_answer("x is 4")
    assert da.answer_expression == "4" and da.answer_variable == "x"
    da = extract_direct_answer("x equals four")
    assert da.answer_expression == "4" and da.answer_variable == "x"
    da = extract_direct_answer("x = 4")
    assert da.answer_expression == "4" and da.answer_variable == "x"


def test_extract_expression_answer():
    assert extract_direct_answer("5x").answer_expression == "5x"
    assert extract_direct_answer("2x + 6").answer_expression == "2x + 6"
    assert extract_direct_answer("three x minus two").answer_expression == "3x - 2"


def test_extract_true_false():
    assert extract_direct_answer("true").answer_expression == "true"
    assert extract_direct_answer("false").answer_expression == "false"


def test_reasoning_sentences_are_not_answers():
    for t in (
        "I add 6 and 14 to get 20 and then divide by 2",
        "I subtract 6 from both sides to get 2x equals 8",
        "First subtract 6 then divide",
        "Because 6 plus 14 is 20",
    ):
        assert extract_direct_answer(t) is None, t


def test_non_answers_rejected():
    for t in ("subtract", "hint", "i don't know", "next problem", "help me", "review"):
        assert extract_direct_answer(t) is None, t


def test_match_operation():
    assert match_operation("subtract", ["subtract"]) == "subtract"
    assert match_operation("subtract 6", ["subtract"]) == "subtract"
    assert match_operation("take away", ["subtract"]) == "subtract"
    assert match_operation("minus", ["subtract"]) == "subtract"
    assert match_operation("divide by 2", ["divide"]) == "divide"
    assert match_operation("division", ["divide"]) == "divide"
    assert match_operation("add 6", ["add"]) == "add"
    assert match_operation("times", ["multiply"]) == "multiply"
    assert match_operation("not subtract", ["subtract"]) is None
