from decimal import Decimal

import pytest

from asset_copilot.calc import MAX_EXPR_LEN, CalcError, calculate


@pytest.mark.parametrize(
    "expr,expected",
    [
        ("1 + 2", "3"),
        ("0.1 + 0.2", "0.3"),  # no float noise
        ("(100 - 80) / 80 * 100", "25"),
        ("2 ** 10", "1024"),
        ("-5 + 3", "-2"),
        ("10 // 3", "3"),
        ("10 % 3", "1"),
        ("round(2.456, 2)", "2.46"),
        ("round(1234.5)", "1234"),  # banker's rounding, matches Python
        ("abs(-3.5)", "3.5"),
        ("max(1, 5, 3)", "5"),
        ("min(4, 2)", "2"),
        ("1200000 * 0.035", "42000.000"),
    ],
)
def test_valid_expressions(expr, expected):
    assert calculate(expr) == Decimal(expected)


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('echo hi')",
        "open('x')",
        "().__class__",
        "x + 1",
        "'a' * 3",
        "True + 1",
        "[1, 2]",
        "lambda: 1",
        "sum([1, 2])",
        "round(1.5, ndigits=1)",
        "abs()",
        "",
        "   ",
        "1 +",
        "1 < 2",
        "1 if 1 else 2",
    ],
)
def test_unsafe_or_invalid_rejected(expr):
    with pytest.raises(CalcError):
        calculate(expr)


def test_division_by_zero():
    with pytest.raises(CalcError, match="Division by zero"):
        calculate("1 / 0")
    with pytest.raises(CalcError, match="Division by zero"):
        calculate("5 // 0")


def test_huge_exponent_rejected():
    with pytest.raises(CalcError):
        calculate("9 ** 9 ** 9")
    with pytest.raises(CalcError):
        calculate("2 ** 0.5")


def test_result_too_large_rejected():
    with pytest.raises(CalcError, match="too large"):
        calculate("10 ** 100")


def test_expression_length_cap():
    with pytest.raises(CalcError, match="longer"):
        calculate("1+" * MAX_EXPR_LEN + "1")


def test_non_string_rejected():
    with pytest.raises(CalcError):
        calculate(None)  # type: ignore[arg-type]
