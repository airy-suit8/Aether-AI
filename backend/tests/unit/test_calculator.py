"""Calculator tool (Task 9): correct results, bounded work (R11, S4)."""

import time

import pytest

from src.agents.tools import calculator


def calc(expression: str) -> str:
    return calculator.invoke(expression)


@pytest.mark.parametrize("expression,expected", [
    ("max(3, 5)", "max(3, 5) = 5"),
    ("min(3, 5)", "min(3, 5) = 3"),
    ("3 x 4", "3 x 4 = 12"),
    ("3x4", "3x4 = 12"),
    ("2 ** 10", "2 ** 10 = 1024"),
    ("2 ^ 10", "2 ^ 10 = 1024"),
    ("sqrt(144)", "sqrt(144) = 12"),
    ("(15 + 25) / 4", "(15 + 25) / 4 = 10"),
])
def test_results(expression, expected):
    assert calc(expression) == expected


def test_no_six_significant_digit_rounding():
    # Was "150000" with the old :.6g format
    assert calc("49999.99 * 3") == "49999.99 * 3 = 149999.97"
    assert calc("1234567.891 + 1") == "1234567.891 + 1 = 1234568.891"


def test_huge_power_is_refused_quickly():
    for expression in ("9**9**9", "(2**1000)**1000", "10**100000"):
        t0 = time.perf_counter()
        result = calc(expression)
        assert time.perf_counter() - t0 < 1.0, expression
        assert result.startswith("Error"), (expression, result)


def test_moderate_power_still_works():
    assert calc("2 ** 64") == "2 ** 64 = 18446744073709551616"


def test_division_by_zero():
    assert calc("1 / 0") == "Error: Division by zero."


@pytest.mark.parametrize("expression,expected", [
    ("-3 + +5", "-3 + +5 = 2"),
    ("7 // 2", "7 // 2 = 3"),
    ("7 % 4", "7 % 4 = 3"),
    ("2 × 3 ÷ 4", "2 × 3 ÷ 4 = 1.5"),
    ("round(2.567, 2)", "round(2.567, 2) = 2.57"),
    ("abs(-4)", "abs(-4) = 4"),
    ("2 * pi", "2 * pi = 6.28318530717959"),
    ("log10(1000)", "log10(1000) = 3"),
    ("0.1 + 0.2", "0.1 + 0.2 = 0.3"),
])
def test_more_operators_and_functions(expression, expected):
    assert calc(expression) == expected


@pytest.mark.parametrize("expression,message", [
    ("'a' + 1", "Unsupported constant"),
    ("1 << 2", "Unsupported operator: LShift"),
    ("~5", "Unsupported unary operator: Invert"),
    ("exp(1)", "Unsupported function: exp"),
    ("__import__('os')", "Unsupported function: __import__"),
    ("y + 1", "Unknown variable: y"),
    ("sqrt", "Unknown variable: sqrt"),
    ("[1, 2]", "Unsupported expression type: List"),
    ("2 +", "Error evaluating"),
])
def test_anything_but_plain_math_is_refused(expression, message):
    result = calc(expression)
    assert result.startswith("Error"), result
    assert message in result
