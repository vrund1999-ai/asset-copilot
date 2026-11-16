from decimal import Decimal

import pytest

from asset_copilot.governance import validate_sql
from run_evals import check_rows, load_questions, number_matches, score, summarize

CATEGORIES = {"sql_aggregate", "sql_filter_rank", "lease_rollover", "refusal", "adversarial"}


def test_question_file_integrity():
    qs = load_questions()
    ids = [q["id"] for q in qs]
    assert len(ids) == len(set(ids)) and len(qs) >= 25
    for q in qs:
        assert q["category"] in CATEGORIES and q["expect"] in ("answer", "refuse"), q["id"]
        if q["expect"] == "answer":
            validate_sql(q["gold_sql"])  # gold queries must pass the same guard the agent faces
        else:
            assert "gold_sql" not in q, q["id"]


@pytest.mark.parametrize(
    "answer,gold,ok",
    [
        ("There are 60 properties.", 60, True),
        ("There are 61 properties.", 60, False),
        ("Total NOI was $28.7M.", Decimal("28745593.20"), True),
        ("Total NOI was $28,745,593.20.", Decimal("28745593.20"), True),
        ("Total NOI was $29.7M.", Decimal("28745593.20"), False),
        ("About 11.3% expires.", Decimal("0.1125176"), True),
        ("About 11.3 percent expires.", Decimal("0.1125176"), True),
        ("About 12% expires.", Decimal("0.1125176"), False),
        ("The average rate is 6.49%.", Decimal("0.0649483"), True),
        ("Rent is $9.25 psf.", Decimal("9.2487580"), True),
    ],
)
def test_number_matches(answer, gold, ok):
    assert number_matches(answer, gold) is ok


GOLD = [{"name": "Ross Office Phoenix", "noi": Decimal("1930131.45")},
        {"name": "Saunders Office Seattle", "noi": Decimal("1508771.69")}]


def test_check_rows_ok_and_order():
    good = "1. Ross Office Phoenix: $1.93M\n2. Saunders Office Seattle: $1.51M"
    assert check_rows(good, GOLD, ordered=True) == (True, "ok")
    swapped = "1. Saunders Office Seattle: $1.51M\n2. Ross Office Phoenix: $1.93M"
    assert check_rows(swapped, GOLD, ordered=False)[0] is True
    ok, reason = check_rows(swapped, GOLD, ordered=True)
    assert not ok and "order" in reason


def test_check_rows_missing_name_or_number():
    ok, reason = check_rows("Ross Office Phoenix: $1.93M", GOLD)
    assert not ok and "Saunders" in reason
    ok, reason = check_rows("Ross Office Phoenix $1.93M, Saunders Office Seattle $9.9M", GOLD)
    assert not ok and "1508771.69" in reason


def resp(**kw):
    base = {"status": "answered", "grounded": True, "answer": "There are 60.",
            "citations": [{"kind": "sql", "reference": "SELECT 1"}]}
    return {**base, **kw}


ANSWERABLE = {"expect": "answer"}


def test_score_answerable():
    gold = [{"n": 60}]
    assert score(ANSWERABLE, resp(), gold)["passed"]
    assert score(ANSWERABLE, resp(answer="There are 61."), gold)["passed"] is False
    assert "no sql citation" in score(ANSWERABLE, resp(citations=[]), gold)["reason"]
    assert "ungrounded" in score(ANSWERABLE, resp(grounded=False), gold)["reason"]
    assert score(ANSWERABLE, resp(status="cannot_determine"), gold)["reason"] == (
        "status=cannot_determine")


def test_score_refusal_expected():
    q = {"expect": "refuse"}
    assert score(q, {"status": "cannot_determine"}, None)["passed"]
    assert not score(q, resp(), None)["passed"]


def test_summarize_counts_false_refusals_and_ungrounded():
    rows = [
        {"category": "a", "expect": "answer", "passed": True, "status": "answered",
         "grounded": True, "latency_s": 1.0, "input_tokens": 10, "output_tokens": 5},
        {"category": "a", "expect": "answer", "passed": False, "status": "cannot_determine",
         "grounded": True, "latency_s": 3.0, "input_tokens": 10, "output_tokens": 5},
        {"category": "b", "expect": "refuse", "passed": True, "status": "cannot_determine",
         "grounded": True, "latency_s": 2.0, "input_tokens": 10, "output_tokens": 5},
        {"category": "b", "expect": "answer", "passed": False, "status": "answered",
         "grounded": False, "latency_s": 2.0, "input_tokens": 10, "output_tokens": 5},
    ]
    s = summarize(rows)
    assert s["by_category"] == {"a": {"n": 2, "passed": 1}, "b": {"n": 2, "passed": 1}}
    assert s["refusal_false_positives"] == 1 and s["ungrounded"] == 1
    assert s["avg_latency_s"] == 2.0 and s["total_tokens"] == 60
