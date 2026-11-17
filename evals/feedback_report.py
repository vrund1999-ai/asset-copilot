"""Summarise the `feedback` table: ratings by kind (chat answers vs variance reports), plus the
thumbs-down items with their corrections, which are the candidates for new eval questions.

    python evals/feedback_report.py                 # print a summary
    python evals/feedback_report.py --export out.jsonl   # write corrected items as eval candidates
"""

import argparse
import json
from collections import Counter

VARIANCE_PREFIX = "[variance]"


def kind_of(question: str) -> str:
    return "variance" if (question or "").startswith(VARIANCE_PREFIX) else "chat"


def summarize(rows: list[dict]) -> dict:
    """rows: dicts with question, answer, rating (-1|1), correction. Pure, no DB."""
    by_kind: dict[str, Counter] = {"chat": Counter(), "variance": Counter()}
    negatives = []
    for r in rows:
        k = kind_of(r["question"])
        by_kind[k]["up" if r["rating"] == 1 else "down"] += 1
        if r["rating"] == -1:
            negatives.append({"kind": k, "question": r["question"], "answer": r["answer"],
                              "correction": r.get("correction")})
    out = {}
    for k, c in by_kind.items():
        total = c["up"] + c["down"]
        out[k] = {"total": total, "up": c["up"], "down": c["down"],
                  "positive_rate": round(c["up"] / total, 4) if total else None}
    return {"total": len(rows), "by_kind": out, "negatives": negatives,
            "with_correction": sum(1 for n in negatives if n["correction"])}


def candidates(summary: dict) -> list[dict]:
    """Corrected thumbs-down chat items, shaped as eval-question stubs for human review."""
    return [{"question": n["question"], "agent_answer": n["answer"],
             "reviewer_correction": n["correction"], "status": "needs_gold_answer"}
            for n in summary["negatives"] if n["kind"] == "chat" and n["correction"]]


def load_rows() -> list[dict]:
    from sqlalchemy import text

    from asset_copilot.db import admin_engine

    with admin_engine().connect() as conn:
        return [dict(r._mapping) for r in conn.execute(text(
            "SELECT question, answer, rating, correction FROM feedback ORDER BY id"))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", help="write corrected chat items to this JSONL file")
    args = ap.parse_args()
    s = summarize(load_rows())
    print(f"feedback rows: {s['total']}")
    for k, v in s["by_kind"].items():
        rate = "n/a" if v["positive_rate"] is None else f"{v['positive_rate']:.0%}"
        print(f"  {k:9s} total={v['total']} up={v['up']} down={v['down']} positive={rate}")
    print(f"thumbs-down: {len(s['negatives'])} ({s['with_correction']} with a correction)")
    for n in s["negatives"]:
        print(f"  - [{n['kind']}] {n['question'][:80]!r} -> {n['correction'] or '(no correction)'}")
    if args.export:
        items = candidates(s)
        with open(args.export, "w", encoding="utf-8") as f:
            f.writelines(json.dumps(i) + "\n" for i in items)
        print(f"wrote {len(items)} eval candidates to {args.export}")


if __name__ == "__main__":
    main()
