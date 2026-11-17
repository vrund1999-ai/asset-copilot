"""Generate the document eval questions from the generated documents + database.

Gold values come from the DB and from the text of the generated documents (never typed by hand), so
they stay correct if the generator changes. Run once and commit the output; the committed file is
the eval set:

    python evals/make_doc_questions.py            # prints JSONL for q031+
    python evals/make_doc_questions.py --write    # replaces any generated rows in questions.jsonl

Requires the portfolio (`--seed 42`) and documents (`synth.documents --seed 42`) to be generated.
Categories: document_lookup, hybrid, reconciliation (seeded discrepancies + clean controls),
and refusals for facts that are not in any document. See docs/EVALS.md.
"""

import argparse
import json
import random
from pathlib import Path

from sqlalchemy import text

from asset_copilot.config import settings
from asset_copilot.db import admin_engine

QUESTIONS = Path(__file__).parent / "questions.jsonl"
FIRST_ID = 31
WORDS = {0: "none", 1: "one", 2: "two", 3: "three"}


def num(v) -> dict:
    return {"kind": "number", "value": float(v)}


def date_fact(iso: str) -> dict:
    return {"kind": "date", "value": iso}


def count_fact(n: int) -> dict:
    options = [str(n), WORDS[n]] + (["no renewal", "no option", "not have any"] if n == 0 else [])
    return {"kind": "text_any", "value": options}


def load(conn, manifest: dict):
    docs = {d["file"]: d for d in manifest["documents"]}
    leases = {r.lease_id: r._mapping for r in conn.execute(text(
        "SELECT l.lease_id, l.suite, l.leased_sq_ft, l.start_date, l.end_date, l.base_rent_psf, "
        "l.annual_escalation, l.renewal_options, l.document_id, p.property_id, "
        "p.name AS prop, t.name AS tenant, t.industry FROM leases l "
        "JOIN properties p USING (property_id) JOIN tenants t USING (tenant_id)"))}
    debts = {r.property_id: r._mapping for r in conn.execute(text(
        "SELECT d.property_id, d.lender, d.principal, d.rate, d.maturity_date, p.name AS prop, "
        "p.sq_ft FROM debt d JOIN properties p USING (property_id)"))}
    return docs, leases, debts


def build(seed: int = 7) -> list[dict]:
    rnd = random.Random(seed)
    base = Path(settings.generated_dir)
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    with admin_engine().connect() as conn:
        docs, leases, debts = load(conn, manifest)
        n_by_tenant_prop = {}
        for r in leases.values():
            key = (r["tenant"], r["property_id"])
            n_by_tenant_prop[key] = n_by_tenant_prop.get(key, 0) + 1

    def text_of(file: str) -> str:
        return (base / file).read_text(encoding="utf-8")

    bad = {d["file"]: d for d in manifest["discrepancies"]}
    lease_docs = [d for d in manifest["documents"] if d["doc_type"] == "lease_abstract"]
    loan_docs = [d for d in manifest["documents"] if d["doc_type"] == "loan_summary"]

    def unique(d) -> bool:
        r = leases[d["lease_id"]]
        return n_by_tenant_prop[(r["tenant"], r["property_id"])] == 1

    clean_leases = [d for d in lease_docs if d["file"] not in bad and unique(d)]
    clean_loans = [d for d in loan_docs if d["file"] not in bad]
    rnd.shuffle(clean_leases)
    rnd.shuffle(clean_loans)
    used: set[str] = set()

    def take(pool, pred=lambda d: True):
        for d in pool:
            if d["file"] not in used and pred(d):
                used.add(d["file"])
                return d
        raise RuntimeError("not enough clean documents for the eval set; regenerate with more")

    def lref(d, r):
        return f"{r['tenant']}'s lease at {r['prop']} ({r['suite']})"

    out: list[dict] = []

    def add(category, question, expect="answer", **extra):
        out.append({"id": f"q{FIRST_ID + len(out):03d}", "category": category,
                    "question": question, "expect": expect, **extra})

    def refs(d, *pages):
        return [f"{d['title']} p.{p}" for p in pages]

    # ---- document_lookup (8): facts that exist only in the document text, or DB == doc ----
    for _ in range(2):
        d = take(clean_leases, lambda d: leases[d["lease_id"]]["renewal_options"] >= 1)
        r = leases[d["lease_id"]]
        add("document_lookup",
            f"How many renewal options does {lref(d, r)} provide, and how long is each extension?",
            gold_refs=refs(d, 2), gold_facts=[count_fact(r["renewal_options"]), num(5)])
    for _ in range(2):
        d = take(clean_leases)
        r = leases[d["lease_id"]]
        add("document_lookup",
            f"When does {lref(d, r)} expire according to its lease abstract?",
            gold_refs=refs(d, 1), gold_facts=[date_fact(r["end_date"].isoformat())])
    for _ in range(2):
        d = take(clean_leases)
        r = leases[d["lease_id"]]
        add("document_lookup",
            f"What base rent per square foot and annual escalation does the lease abstract for "
            f"{lref(d, r)} state?",
            gold_refs=refs(d, 2),
            gold_facts=[num(r["base_rent_psf"]), num(r["annual_escalation"])])
    for _ in range(2):
        d = take(clean_loans)
        r = debts[d["property_id"]]
        add("document_lookup",
            f"According to its loan summary, what is the interest rate and the maturity date of "
            f"the loan on {r['prop']}?",
            gold_refs=refs(d, 1),
            gold_facts=[num(r["rate"]), date_fact(r["maturity_date"].isoformat())])

    # ---- hybrid (6): one fact from SQL, one from the document text ----
    for _ in range(2):
        d = take(clean_leases, lambda d: leases[d["lease_id"]]["renewal_options"] >= 1)
        r = leases[d["lease_id"]]
        add("hybrid",
            f"What is the leased square footage of {r['tenant']}'s space at {r['prop']} "
            f"({r['suite']}), and how many renewal options does its lease abstract give?",
            gold_sql=f"SELECT leased_sq_ft FROM leases WHERE lease_id = {r['lease_id']}",
            gold_refs=refs(d, 2), gold_facts=[count_fact(r["renewal_options"])])
    for _ in range(2):
        d = take(clean_leases, lambda d: "$2,000,000" in text_of(d["file"]))
        r = leases[d["lease_id"]]
        add("hybrid",
            f"What industry is {r['tenant']} in, and what liability insurance coverage per "
            f"occurrence must it maintain under its lease at {r['prop']} ({r['suite']})?",
            gold_sql=f"SELECT t.industry FROM leases l JOIN tenants t USING (tenant_id) "
                     f"WHERE l.lease_id = {r['lease_id']}",
            gold_refs=refs(d, 3), gold_facts=[num(2_000_000)])
    for _ in range(2):
        d = take(clean_loans, lambda d: "within 45 days" in text_of(d["file"]))
        r = debts[d["property_id"]]
        add("hybrid",
            f"What is the outstanding loan principal on {r['prop']}, and within how many days of "
            f"quarter end must the borrower deliver operating statements?",
            gold_sql=f"SELECT principal FROM debt WHERE property_id = {r['property_id']}",
            gold_refs=refs(d, 2), gold_facts=[num(45)])

    # ---- reconciliation: every seeded discrepancy, plus clean controls ----
    prompts = {
        "end_date": "When does {who} expire, and does its lease abstract match our records?",
        "base_rent_psf": "What base rent per square foot does the lease abstract state for {who}, "
                         "and does it match the database?",
        "renewal_options": "How many renewal options does the lease abstract give for {who}, and "
                           "does that match our records?",
        "annual_escalation": "What annual escalation does the lease abstract state for {who}, and "
                             "does it match the database?",
        "maturity_date": "What maturity date does the loan summary for {prop} state, and does it "
                         "match our debt records?",
        "rate": "What interest rate does the loan summary for {prop} state, and does it match our "
                "debt records?",
    }

    def fact(field, v):
        if field in ("end_date", "maturity_date"):
            return date_fact(str(v))
        if field == "renewal_options":
            return count_fact(int(v))
        return num(v)

    for item in manifest["discrepancies"]:
        d = docs[item["file"]]
        if item["entity"] == "lease":
            r = leases[item["entity_id"]]
            q = prompts[item["field"]].format(who=lref(d, r))
        else:
            q = prompts[item["field"]].format(prop=debts[item["entity_id"]]["prop"])
        add("reconciliation", q, expect_discrepancy=True, gold_refs=refs(d, item["page"]),
            gold_facts=[fact(item["field"], item["db_value"]),
                        fact(item["field"], item["doc_value"])],
            seeded_field=item["field"])

    controls = [("end_date", "lease"), ("base_rent_psf", "lease"),
                ("annual_escalation", "lease"), ("rate", "debt")]
    for field, entity in controls:
        if entity == "lease":
            d = take(clean_leases)
            r = leases[d["lease_id"]]
            q = prompts[field].format(who=lref(d, r))
            val = r[field].isoformat() if field == "end_date" else r[field]
            page = 1 if field == "end_date" else 2
        else:
            d = take(clean_loans)
            r = debts[d["property_id"]]
            q = prompts[field].format(prop=r["prop"])
            val, page = r[field], 1
        add("reconciliation", q, expect_discrepancy=False, gold_refs=refs(d, page),
            gold_facts=[fact(field, val)], seeded_field=None)

    # ---- refusals: facts that no document states ----
    for topic in ("tenant improvement allowance", "parking ratio"):
        d = take(clean_leases)
        r = leases[d["lease_id"]]
        add("refusal", f"What is the {topic} in {lref(d, r)}?", expect="refuse")
    for topic in ("debt service coverage covenant", "guarantor"):
        d = take(clean_loans)
        r = debts[d["property_id"]]
        add("refusal", f"What is the {topic} in the loan on {r['prop']}?", expect="refuse")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    qs = build()
    lines = [json.dumps(q) for q in qs]
    if not args.write:
        print("\n".join(lines))
        return
    kept = [ln for ln in QUESTIONS.read_text().splitlines()
            if ln.strip() and int(json.loads(ln)["id"][1:]) < FIRST_ID]
    QUESTIONS.write_text("\n".join(kept + lines) + "\n")
    print(f"Wrote {len(kept)} existing + {len(lines)} generated questions to {QUESTIONS}")


if __name__ == "__main__":
    main()
