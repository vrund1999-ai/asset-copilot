"""Compare two eval runs: per-category accuracy before/after and which questions flipped.

    python evals/compare_runs.py                  # the two most recent full runs
    python evals/compare_runs.py OLD.json NEW.json
    python evals/compare_runs.py --history        # one line per full run, oldest first

A "full run" is a results file covering at least --min-questions questions (default 50), so the
small smoke runs and retrieval-*.json files are ignored when picking runs automatically.
"""

import argparse
import json
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def accuracy(run: dict) -> dict[str, tuple[int, int]]:
    """category -> (passed, n), plus 'OVERALL'."""
    out: dict[str, list[int]] = {}
    for r in run["results"]:
        c = out.setdefault(r["category"], [0, 0])
        c[0] += bool(r["passed"])
        c[1] += 1
    total = (sum(p for p, _ in out.values()), sum(n for _, n in out.values()))
    return {**{k: (v[0], v[1]) for k, v in sorted(out.items())}, "OVERALL": total}


def compare(old: dict, new: dict) -> dict:
    """Pure comparison. Questions are matched by id; only ids present in both count as flips."""
    o = {r["id"]: r for r in old["results"]}
    n = {r["id"]: r for r in new["results"]}
    common = sorted(set(o) & set(n))
    fixed = [i for i in common if not o[i]["passed"] and n[i]["passed"]]
    regressed = [i for i in common if o[i]["passed"] and not n[i]["passed"]]
    return {"old": accuracy(old), "new": accuracy(new), "fixed": fixed, "regressed": regressed,
            "added": sorted(set(n) - set(o)), "removed": sorted(set(o) - set(n)),
            "reasons": {i: n[i]["reason"] for i in regressed}}


def format_report(c: dict) -> str:
    def cell(t):
        return f"{t[0]}/{t[1]} ({t[0] / t[1]:.0%})" if t and t[1] else "-"

    lines = [f"{'category':<18}{'before':>16}{'after':>16}"]
    for cat in [k for k in c["new"] if k != "OVERALL"] + [k for k in c["old"] if k not in c["new"]]:
        lines.append(f"{cat:<18}{cell(c['old'].get(cat)):>16}{cell(c['new'].get(cat)):>16}")
    lines.append(f"{'OVERALL':<18}{cell(c['old']['OVERALL']):>16}{cell(c['new']['OVERALL']):>16}")
    lines.append(f"\nfixed: {', '.join(c['fixed']) or 'none'}")
    lines.append(f"regressed: {', '.join(c['regressed']) or 'none'}")
    for i, why in c["reasons"].items():
        lines.append(f"  {i}: {why}")
    if c["added"]:
        lines.append(f"new questions (not comparable): {len(c['added'])}")
    return "\n".join(lines)


def full_runs(min_questions: int = 50) -> list[Path]:
    paths = []
    for p in sorted(RESULTS_DIR.glob("2*.json")):  # timestamped runs; retrieval-*.json excluded
        try:
            if load(p)["summary"]["overall"]["n"] >= min_questions:
                paths.append(p)
        except (KeyError, ValueError):
            continue
    return paths


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--history", action="store_true")
    ap.add_argument("--min-questions", type=int, default=50)
    args = ap.parse_args()
    runs = full_runs(args.min_questions)
    if args.history:
        for p in runs:
            o = load(p)["summary"]["overall"]
            print(f"{p.stem}  {o['passed']}/{o['n']}  {o['passed'] / o['n']:.0%}")
        return
    if len(args.files) == 2:
        old, new = args.files
    elif len(runs) >= 2:
        old, new = runs[-2], runs[-1]
    else:
        raise SystemExit("need two full runs; pass two files or run run_evals.py first")
    print(f"before: {old.name}\nafter:  {new.name}\n")
    print(format_report(compare(load(old), load(new))))


if __name__ == "__main__":
    main()
