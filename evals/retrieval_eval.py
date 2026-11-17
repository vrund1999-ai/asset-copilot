"""Retrieval hit-rate@k for the document questions (no LLM involved).

For every question with `gold_refs` ("<title> p.<n>"), run the question text through
`retrieval.search` unfiltered, and check whether the gold document (and the gold document+page) is
among the top-k matched chunks. This isolates retrieval quality from the agent's behaviour.

Usage:  python evals/retrieval_eval.py          # needs Postgres with ingested documents
"""

import json
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from run_evals import RESULTS_DIR, load_questions

KS = (1, 3)


def _doc_of(ref: str) -> str:
    return ref.rsplit(" p.", 1)[0]


def retrieval_metrics(
    questions: list[dict], search_fn: Callable[[str], list[dict]], ks: tuple[int, ...] = KS
) -> dict:
    """search_fn(question) -> chunk dicts (title, page, expanded) ranked by similarity."""
    per_cat: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    details = []
    for q in questions:
        gold = set(q["gold_refs"])
        gold_docs = {_doc_of(r) for r in gold}
        ranked = [r for r in search_fn(q["question"]) if not r.get("expanded")]
        refs = [f"{r['title']} p.{r['page']}" for r in ranked]
        row = {"id": q["id"], "category": q["category"], "top_ref": refs[0] if refs else None}
        per_cat[q["category"]]["n"] += 1
        for k in ks:
            doc_hit = any(_doc_of(r) in gold_docs for r in refs[:k])
            page_hit = any(r in gold for r in refs[:k])
            per_cat[q["category"]][f"doc@{k}"] += doc_hit
            per_cat[q["category"]][f"page@{k}"] += page_hit
            row[f"doc@{k}"], row[f"page@{k}"] = doc_hit, page_hit
        details.append(row)
    overall: dict[str, int] = defaultdict(int)
    for stats in per_cat.values():
        for key, v in stats.items():
            overall[key] += v
    return {"by_category": {c: dict(s) for c, s in per_cat.items()}, "overall": dict(overall),
            "details": details}


def print_table(m: dict, ks: tuple[int, ...] = KS) -> None:
    cols = [f"{kind}@{k}" for k in ks for kind in ("doc", "page")]
    print(f"\n{'category':<20}{'n':>4}" + "".join(f"{c:>10}" for c in cols))
    rows = sorted(m["by_category"].items()) + [("OVERALL", m["overall"])]
    for cat, s in rows:
        n = s["n"]
        print(f"{cat:<20}{n:>4}" + "".join(f"{s.get(c, 0) / max(n, 1):>10.0%}" for c in cols))


def main() -> None:
    from asset_copilot.retrieval import search

    qs = [q for q in load_questions() if q.get("gold_refs")]
    metrics = retrieval_metrics(qs, lambda text: search(text, top_k=max(KS)))
    print_table(metrics)
    RESULTS_DIR.mkdir(exist_ok=True)
    out = Path(RESULTS_DIR) / f"retrieval-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps(metrics, indent=2, default=int))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
