from decimal import Decimal

import pytest

from asset_copilot.grounding import extract_numbers, find_ungrounded
from asset_copilot.tools import CalcRecord, QueryRecord


def q(rows, id_="Q1"):
    return QueryRecord(id_, "SELECT 1", "", list(rows[0]) if rows else [], rows)


def c(result, id_="C1"):
    return CalcRecord(id_, "x", "", Decimal(result))


@pytest.mark.parametrize(
    "answer,rows",
    [
        ("The portfolio has 60 properties [Q1].", [{"n": 60}]),
        ("Total NOI was $12,345,678.90 [Q1].", [{"total_noi": "12345678.90"}]),
        ("Total NOI was about $12.3M [Q1].", [{"total_noi": "12345678.90"}]),
        ("Total NOI was 12.35 million [Q1].", [{"total_noi": "12345678.90"}]),
        ("NOI margin was 43.2% [Q1].", [{"margin": "0.432"}]),
        ("NOI margin was 43.2% [Q1].", [{"margin": 43.2}]),
        ("Occupancy fell 5%.", [{"delta": "-5"}]),  # sign ignored
        ("There are 3 results [Q1].", [{"a": 1}, {"a": 2}, {"a": 3}]),  # row count
        ("As of 2026-06-30 there are 60 properties.", [{"n": 60}]),  # ISO date exempt
        ("In June 2026 the count was 60.", [{"n": 60}]),  # month-year exempt
        ("1. Dallas has 7.\n2. Miami has 4.", [{"a": 7}, {"b": 4}]),  # list indexes exempt
    ],
)
def test_grounded(answer, rows):
    assert find_ungrounded(answer, "question", [q(rows)], []) == []


@pytest.mark.parametrize(
    "answer,rows,expected",
    [
        ("There are 61 properties.", [{"n": 60}], ["61"]),
        ("NOI was $12.9M.", [{"v": "12345678"}], ["12.9M"]),
        ("Occupancy is 87.5%.", [{"occ": "0.91"}], ["87.5%"]),
        ("Rent is 25.50 psf and there are 9 tenants.", [{"rent": "25.50"}], ["9"]),
    ],
)
def test_ungrounded_detected(answer, rows, expected):
    assert find_ungrounded(answer, "question", [q(rows)], []) == expected


def test_calc_results_count_as_grounded():
    assert find_ungrounded("The variance is 12.5%.", "q", [q([{"x": 1}])], [c("12.5")]) == []


def test_numbers_from_question_are_grounded():
    # "18" came from the user, not the tool.
    assert find_ungrounded("Over the next 18 months, 7 leases expire.", "next 18 months?",
                           [q([{"n": 7}])], []) == []


def test_only_cited_results_count():
    # Q2 has the number but is not passed in as cited.
    assert find_ungrounded("There are 99.", "q", [q([{"n": 1}], "Q1")], []) == ["99"]


def test_trailing_punctuation_not_part_of_number():
    assert find_ungrounded("Revenue was 1,200, costs 800.", "q", [q([{"r": 1200, "c": 800}])], []) == []


def test_extract_numbers_precision_sets_tolerance():
    (_, value, tol, is_pct), = extract_numbers("$1.2M")
    assert value == Decimal(1200000) and tol > Decimal(50000) and not is_pct
