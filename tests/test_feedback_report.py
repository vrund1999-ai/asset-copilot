import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "evals"))

from feedback_report import candidates, kind_of, summarize

ROWS = [
    {"question": "Which assets roll?", "answer": "A", "rating": 1, "correction": None},
    {"question": "Total NOI?", "answer": "B", "rating": -1, "correction": "should be 5"},
    {"question": "Vacancy?", "answer": "C", "rating": -1, "correction": None},
    {"question": "[variance] Entire portfolio 2026-06", "answer": "D", "rating": 1,
     "correction": None},
    {"question": "[variance] Foo 2026-05", "answer": "E", "rating": -1, "correction": "too vague"},
]


def test_kind_of():
    assert kind_of("[variance] x") == "variance" and kind_of("hello") == "chat"
    assert kind_of(None) == "chat"


def test_summarize_counts_by_kind():
    s = summarize(ROWS)
    assert s["total"] == 5 and s["with_correction"] == 2
    assert s["by_kind"]["chat"] == {"total": 3, "up": 1, "down": 2, "positive_rate": 0.3333}
    assert s["by_kind"]["variance"] == {"total": 2, "up": 1, "down": 1, "positive_rate": 0.5}
    assert len(s["negatives"]) == 3


def test_empty_has_no_rate():
    s = summarize([])
    assert s["by_kind"]["chat"]["positive_rate"] is None and s["negatives"] == []


def test_candidates_are_corrected_chat_negatives_only():
    c = candidates(summarize(ROWS))
    assert [x["question"] for x in c] == ["Total NOI?"]
    assert c[0]["reviewer_correction"] == "should be 5"
