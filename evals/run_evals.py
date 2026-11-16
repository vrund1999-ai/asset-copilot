"""Eval harness.

For each question in questions.jsonl:
  1. Run the gold SQL on the read-only role to get the expected result (answerable questions).
  2. Ask the agent (POST /ask) and score the response.
  3. Print per-category accuracy and write evals/results/<timestamp>.json.

Everything numeric is scored in code, never by a model. See docs/EVALS.md.

Usage:
  python evals/run_evals.py                   # all questions against http://localhost:8000
  python evals/run_evals.py --category refusal --limit 3
  python evals/run_evals.py --ids q001,q002
"""

import argparse
import json
import time
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx

from asset_copilot.grounding import extract_numbers

QUESTIONS = Path(__file__).parent / "questions.jsonl"
RESULTS_DIR = Path(__file__).parent / "results"
REL_TOL = Decimal("0.005")  # 0.5% for numeric answers


def load_questions() -> list[dict]:
    return [json.loads(line) for line in QUESTIONS.read_text().splitlines() if line.strip()]


def number_matches(answer: str, gold, rel: Decimal = REL_TOL) -> bool:
    """True if some number in `answer` equals `gold` within 0.5% or the precision it was written at.

    Percentages are matched against both the written value and value/100, because gold SQL often
    returns a fraction (0.112) while the answer says "11.2%".
    """
    g = abs(Decimal(str(gold)))
    for _, value, tol, is_pct in extract_numbers(answer):
        value = abs(value)
        candidates = [(value, tol)]
        if is_pct:
            candidates.append((value / 100, tol / 100))
        if any(abs(v - g) <= max(g * rel, t) for v, t in candidates):
            return True
    return False


def _is_number(v) -> bool:
    return isinstance(v, int | float | Decimal) and not isinstance(v, bool)


def check_rows(answer: str, gold: list[dict], ordered: bool = False) -> tuple[bool, str]:
    """Compare an answer to gold rows: names must appear, numbers must match, order if ordered."""
    low = answer.lower()
    positions = []
    for i, row in enumerate(gold):
        for col, v in row.items():
            if _is_number(v):
                if not number_matches(answer, v):
                    return False, f"row {i + 1}: {col}={v} not found in answer"
            elif v is not None:
                pos = low.find(str(v).lower())
                if pos < 0:
                    return False, f"row {i + 1}: '{v}' not found in answer"
                positions.append(pos)
    if ordered and positions != sorted(positions):
        return False, "rows appear in the wrong order"
    return True, "ok"


def score(q: dict, resp: dict, gold: list[dict] | None) -> dict:
    """Score one response. Returns {passed, reason}."""
    status = resp.get("status")
    if q["expect"] == "refuse":
        ok = status == "cannot_determine"
        return {"passed": ok, "reason": "ok" if ok else f"expected refusal, got status={status}"}

    if status != "answered":
        return {"passed": False, "reason": f"status={status}"}
    if not any(c["kind"] == "sql" for c in resp.get("citations", [])):
        return {"passed": False, "reason": "no sql citation"}
    if not resp.get("grounded", False):
        return {"passed": False, "reason": "ungrounded numbers in answer"}
    ok, reason = check_rows(resp["answer"], gold or [], q.get("ordered", False))
    return {"passed": ok, "reason": reason}


def run_one(client: httpx.Client, url: str, q: dict) -> tuple[dict, float]:
    start = time.perf_counter()
    r = client.post(f"{url}/ask", json={"question": q["question"]}, timeout=300)
    r.raise_for_status()
    return r.json(), time.perf_counter() - start


def summarize(results: list[dict]) -> dict:
    by_cat = defaultdict(lambda: {"n": 0, "passed": 0})
    for r in results:
        by_cat[r["category"]]["n"] += 1
        by_cat[r["category"]]["passed"] += r["passed"]
    answerable = [r for r in results if r["expect"] == "answer"]
    refused_answerable = sum(r.get("status") == "cannot_determine" for r in answerable)
    return {
        "overall": {"n": len(results), "passed": sum(r["passed"] for r in results)},
        "by_category": dict(by_cat),
        "refusal_false_positives": refused_answerable,  # answerable questions wrongly refused
        "ungrounded": sum(r.get("grounded") is False for r in results),
        "avg_latency_s": round(sum(r["latency_s"] for r in results) / max(len(results), 1), 2),
        "total_tokens": sum(r.get("input_tokens", 0) + r.get("output_tokens", 0) for r in results),
    }


def print_table(summary: dict) -> None:
    print(f"\n{'category':<18}{'passed':>8}{'n':>6}{'accuracy':>10}")
    for cat, s in sorted(summary["by_category"].items()):
        print(f"{cat:<18}{s['passed']:>8}{s['n']:>6}{s['passed'] / s['n']:>10.0%}")
    o = summary["overall"]
    print(f"{'OVERALL':<18}{o['passed']:>8}{o['n']:>6}{o['passed'] / max(o['n'], 1):>10.0%}")
    print(f"\nanswerable questions wrongly refused: {summary['refusal_false_positives']}")
    print(f"ungrounded answers: {summary['ungrounded']}")
    print(f"avg latency: {summary['avg_latency_s']}s   total tokens: {summary['total_tokens']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--category")
    ap.add_argument("--ids", help="comma-separated question ids")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    from asset_copilot.db import run_readonly_query

    qs = load_questions()
    if args.category:
        qs = [q for q in qs if q["category"] == args.category]
    if args.ids:
        wanted = set(args.ids.split(","))
        qs = [q for q in qs if q["id"] in wanted]
    if args.limit:
        qs = qs[: args.limit]

    results = []
    with httpx.Client() as client:
        for q in qs:
            gold = run_readonly_query(q["gold_sql"]) if q.get("gold_sql") else None
            try:
                resp, latency = run_one(client, args.url, q)
            except httpx.HTTPError as e:
                results.append({"id": q["id"], "category": q["category"], "expect": q["expect"],
                                "passed": False, "reason": f"request failed: {e}",
                                "latency_s": 0.0})
                print(f"{q['id']} ERROR  {e}")
                continue
            verdict = score(q, resp, gold)
            usage = resp.get("usage", {})
            results.append({
                "id": q["id"], "category": q["category"], "expect": q["expect"],
                "question": q["question"], **verdict, "status": resp.get("status"),
                "grounded": resp.get("grounded"), "answer": resp.get("answer"),
                "citations": resp.get("citations"), "steps": resp.get("steps"),
                "latency_s": round(latency, 2),
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "gold": json.loads(json.dumps(gold, default=str)) if gold is not None else None,
            })
            print(f"{q['id']} {'PASS' if verdict['passed'] else 'FAIL'}  {verdict['reason']}")

    summary = summarize(results)
    print_table(summary)
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps({"summary": summary, "results": results}, indent=2))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
