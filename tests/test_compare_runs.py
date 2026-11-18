import json

import pytest

import compare_runs
from compare_runs import accuracy, compare, format_report, full_runs
from run_evals import load_questions, summarize


def run(*rows):
    return {"results": [{"id": i, "category": c, "passed": p, "reason": r, "expect": "answer",
                         "latency_s": 1.0} for i, c, p, r in rows]}


OLD = run(("q1", "sql_aggregate", True, "ok"), ("q2", "sql_aggregate", False, "bad"),
          ("q3", "refusal", True, "ok"), ("q4", "refusal", False, "bad"))
NEW = run(("q1", "sql_aggregate", True, "ok"), ("q2", "sql_aggregate", True, "ok"),
          ("q3", "refusal", False, "expected refusal, got status=answered"),
          ("q4", "refusal", False, "bad"), ("q5", "refusal", True, "ok"))


def test_accuracy_by_category_and_overall():
    a = accuracy(NEW)
    assert a["sql_aggregate"] == (2, 2) and a["refusal"] == (1, 3) and a["OVERALL"] == (3, 5)


def test_compare_finds_fixed_regressed_and_added():
    c = compare(OLD, NEW)
    assert c["fixed"] == ["q2"] and c["regressed"] == ["q3"] and c["added"] == ["q5"]
    assert c["reasons"] == {"q3": "expected refusal, got status=answered"} and c["removed"] == []


def test_report_text_has_before_after_and_flips():
    text = format_report(compare(OLD, NEW))
    assert "1/2 (50%)" in text and "2/2 (100%)" in text and "fixed: q2" in text
    assert "regressed: q3" in text and "OVERALL" in text


def test_report_with_no_changes():
    text = format_report(compare(OLD, OLD))
    assert "fixed: none" in text and "regressed: none" in text


def test_full_runs_skips_small_and_retrieval_files(tmp_path, monkeypatch):
    def write(name, n):
        (tmp_path / name).write_text(json.dumps({"summary": {"overall": {"n": n, "passed": n}},
                                                 "results": []}))
    write("20260101T000000Z.json", 112)
    write("20260102T000000Z.json", 2)
    write("retrieval-20260103T000000Z.json", 112)
    (tmp_path / "20260104T000000Z.json").write_text("not json")
    monkeypatch.setattr(compare_runs, "RESULTS_DIR", tmp_path)
    assert [p.name for p in full_runs()] == ["20260101T000000Z.json"]


def test_summarize_counts_data_modified():
    rs = [{"category": "adversarial", "expect": "refuse", "passed": False, "latency_s": 1,
           "data_modified": True},
          {"category": "adversarial", "expect": "refuse", "passed": True, "latency_s": 1}]
    assert summarize(rs)["data_modified"] == 1


MINIMUMS = {"sql_aggregate": 30, "sql_filter_rank": 20, "lease_rollover": 15, "refusal": 10,
            "adversarial": 10}


def test_question_set_meets_category_targets():
    qs = load_questions()
    assert len(qs) >= 100
    counts = {c: sum(q["category"] == c for q in qs) for c in MINIMUMS}
    for cat, n in MINIMUMS.items():
        assert counts[cat] >= n, (cat, counts[cat])


@pytest.mark.integration
def test_every_gold_sql_runs_and_returns_data(live_db):
    from asset_copilot.db import run_readonly_query

    for q in load_questions():
        if "gold_sql" not in q:
            continue
        rows = run_readonly_query(q["gold_sql"])
        assert rows, q["id"]
        assert any(v is not None for r in rows for v in r.values()), q["id"]
