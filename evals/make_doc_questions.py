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
import re
from pathlib import Path

from sqlalchemy import text

from asset_copilot.config import settings
from asset_copilot.db import admin_engine

QUESTIONS = Path(__file__).parent / "questions.jsonl"
FIRST_ID = 31
LEGACY_N = 30  # q031-q060 predate id decoupling; later additions get fresh ids
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
        # Ids are assigned in main(): the first LEGACY_N keep q031.., later rows get fresh ids.
        out.append({"id": None, "category": category, "question": question, "expect": expect,
                    "generated": True, **extra})

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
    # ---- harder document questions (appended last so earlier picks are unchanged) ----
    # Facts below exist ONLY in the document text; gold values are parsed from it. Documents may
    # be reused here (different facts), so these draw from pools without the `used` constraint.
    def pick(pool, pred):
        ok = [d for d in pool if pred(d)]
        if not ok:
            raise RuntimeError("no document satisfies the predicate; regenerate with more")
        return rnd.choice(ok)

    def holdover(d):
        m = re.search(r"is (\d+)% of the rent in effect for the first (\d+) days and (\d+)% "
                      r"thereafter", text_of(d["file"]))
        return tuple(int(x) for x in m.groups())

    def renewal_terms(d):
        m = re.search(r"at (\d+)% of fair market rent, exercisable on (\d+) months",
                      text_of(d["file"]))
        return int(m.group(1)), int(m.group(2))

    def insurance(d):
        m = re.search(r"not less than \$([\d,]+) per occurrence", text_of(d["file"]))
        return int(m.group(1).replace(",", ""))

    def reporting(d):
        m = re.search(r"within (\d+) days of quarter end and audited annual statements within "
                      r"(\d+) days", text_of(d["file"]))
        return int(m.group(1)), int(m.group(2))

    def has_holdover(d):
        return bool(re.search(r"first \d+ days and \d+% thereafter", text_of(d["file"])))

    def has_renewal(d):
        return leases[d["lease_id"]]["renewal_options"] >= 1 and bool(
            re.search(r"fair market rent, exercisable on", text_of(d["file"])))

    def nonrecourse(d):
        return "non-recourse" in text_of(d["file"])

    def has_report(d):
        return bool(re.search(r"audited annual statements within", text_of(d["file"])))

    def has_ins(d):
        return bool(re.search(r"not less than \$[\d,]+ per occurrence", text_of(d["file"])))

    def anything(d):
        return True

    d = pick(clean_leases, has_holdover)
    r = leases[d["lease_id"]]
    h = holdover(d)
    add("document_lookup",
        f"If {r['tenant']} stays past the end of its lease at {r['prop']} ({r['suite']}), what "
        f"percentage of its normal rent does it pay for the first {h[1]} days, and what percentage "
        f"after that?",
        gold_refs=refs(d, 3), gold_facts=[num(h[0]), num(h[2])])
    d = pick(clean_leases, has_renewal)
    r = leases[d["lease_id"]]
    t = renewal_terms(d)
    add("document_lookup",
        f"What share of fair market rent would {r['tenant']} pay if it exercises a renewal option "
        f"at {r['prop']} ({r['suite']}), and how many months notice must it give?",
        gold_refs=refs(d, 2), gold_facts=[num(t[0]), num(t[1])])
    d = pick(clean_leases, anything)
    r = leases[d["lease_id"]]
    add("document_lookup",
        f"On what date did {lref(d, r)} commence, according to the lease abstract?",
        gold_refs=refs(d, 1), gold_facts=[date_fact(r["start_date"].isoformat())])
    d = pick(clean_leases, has_ins)
    r = leases[d["lease_id"]]
    add("document_lookup",
        f"What is the minimum liability insurance coverage per occurrence that {r['tenant']} must "
        f"carry at {r['prop']} ({r['suite']})?",
        gold_refs=refs(d, 3), gold_facts=[num(insurance(d))])
    d = pick(clean_loans, nonrecourse)
    r = debts[d["property_id"]]
    add("document_lookup",
        f"Is the loan on {r['prop']} recourse or non-recourse to the borrower?",
        gold_refs=refs(d, 2),
        gold_facts=[{"kind": "text_any", "value": ["non-recourse", "nonrecourse"]}])
    d = pick(clean_loans, has_report)
    r = debts[d["property_id"]]
    add("document_lookup",
        f"How many days after year end does the borrower of the {r['prop']} loan have to deliver "
        f"audited annual statements?",
        gold_refs=refs(d, 2), gold_facts=[num(reporting(d)[1])])
    d = pick(clean_loans, anything)
    r = debts[d["property_id"]]
    add("document_lookup",
        f"Which bank lends on {r['prop']}, and what was the original principal in the loan "
        f"summary?",
        gold_refs=refs(d, 1),
        gold_facts=[{"kind": "text_any", "value": [r["lender"]]}, num(r["principal"])])

    d = pick(clean_leases, has_holdover)
    r = leases[d["lease_id"]]
    add("hybrid",
        f"What is the annual base rent in dollars (rent per square foot times leased square feet) "
        f"for {r['tenant']}'s lease at {r['prop']} ({r['suite']}), and what percentage of normal "
        f"rent is charged in holdover for the first {holdover(d)[1]} days?",
        gold_sql=f"SELECT base_rent_psf * leased_sq_ft AS annual_rent FROM leases "
                 f"WHERE lease_id = {r['lease_id']}",
        gold_refs=refs(d, 3), gold_facts=[num(holdover(d)[0])])
    d = pick(clean_loans, has_report)
    r = debts[d["property_id"]]
    add("hybrid",
        f"How many days from June 30, 2026 until the loan on {r['prop']} matures, and how many "
        f"days does the borrower have to deliver audited annual statements?",
        gold_sql=f"SELECT (maturity_date - DATE '2026-06-30') AS days FROM debt "
                 f"WHERE property_id = {r['property_id']}",
        gold_refs=refs(d, 2), gold_facts=[num(reporting(d)[1])])
    d = pick(clean_loans, nonrecourse)
    r = debts[d["property_id"]]
    lender = r["lender"].replace("'", "''")
    add("hybrid",
        f"How many loans in the portfolio does {r['lender']} hold, and is the loan on "
        f"{r['prop']} recourse or non-recourse?",
        gold_sql=f"SELECT COUNT(*) AS n FROM debt WHERE lender = '{lender}'",
        gold_refs=refs(d, 2),
        gold_facts=[{"kind": "text_any", "value": ["non-recourse", "nonrecourse"]}])
    d = pick(clean_leases, has_holdover)
    r = leases[d["lease_id"]]
    add("hybrid",
        f"How many square feet does {r['tenant']} lease at {r['prop']} ({r['suite']}) according "
        f"to our database, and for how many days is holdover charged at the first-tier rate in "
        f"its lease?",
        gold_sql=f"SELECT leased_sq_ft FROM leases WHERE lease_id = {r['lease_id']}",
        gold_refs=refs(d, 3), gold_facts=[num(holdover(d)[1])])

    # Reconciliation, reworded so the question states the database value and asks for a check
    # (the original wording never gave the value). Seeded mismatches must still be flagged.
    by_field = {}
    for item in manifest["discrepancies"]:
        by_field.setdefault(item["field"], item)

    def shown(field, v):
        return f"{float(v) * 100:.2f}%" if field == "rate" else str(v)

    templates = {
        "end_date": ("Our system shows {who} ending on {db}. Can you check that against its "
                     "lease abstract?"),
        "renewal_options": ("Our records say {who} has {db} renewal option(s). Does its lease "
                            "abstract agree?"),
        "maturity_date": ("Our debt records show the loan on {prop} maturing on {db}. Is that "
                          "what the loan summary says?"),
        "rate": ("The database lists the interest rate on the {prop} loan as {db}. Does the "
                 "loan summary say the same?"),
    }
    for field, tmpl in templates.items():
        item = by_field[field]
        d = docs[item["file"]]
        if item["entity"] == "lease":
            who, prop = lref(d, leases[item["entity_id"]]), None
        else:
            who, prop = None, debts[item["entity_id"]]["prop"]
        add("reconciliation", tmpl.format(who=who, prop=prop, db=shown(field, item["db_value"])),
            expect_discrepancy=True, gold_refs=refs(d, item["page"]),
            gold_facts=[fact(field, item["db_value"]), fact(field, item["doc_value"])],
            seeded_field=field)
    d = pick(clean_leases, anything)
    r = leases[d["lease_id"]]
    add("reconciliation",
        f"Our system shows {lref(d, r)} ending on {r['end_date'].isoformat()}. Can you check "
        f"that against its lease abstract?",
        expect_discrepancy=False, gold_refs=refs(d, 1),
        gold_facts=[date_fact(r["end_date"].isoformat())], seeded_field=None)
    d = pick(clean_loans, anything)
    r = debts[d["property_id"]]
    add("reconciliation",
        f"The database lists the interest rate on the {r['prop']} loan as "
        f"{float(r['rate']) * 100:.2f}%. Does the loan summary say the same?",
        expect_discrepancy=False, gold_refs=refs(d, 1), gold_facts=[num(r["rate"])],
        seeded_field=None)
    return out


def is_generated(row: dict) -> bool:
    """Rows this script owns: flagged, or the original q031-q060 block written before the flag."""
    n = int(row["id"][1:])
    return bool(row.get("generated")) or FIRST_ID <= n < FIRST_ID + LEGACY_N


def assign_ids(qs: list[dict], hand_written: list[dict]) -> None:
    """First LEGACY_N keep q031..; the rest get ids after the highest id in the file."""
    next_free = max([int(r["id"][1:]) for r in hand_written] + [FIRST_ID + LEGACY_N - 1]) + 1
    for i, q in enumerate(qs):
        if i < LEGACY_N:
            q["id"] = f"q{FIRST_ID + i:03d}"
        else:
            q["id"] = f"q{next_free:03d}"
            next_free += 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    existing = [json.loads(ln) for ln in QUESTIONS.read_text(encoding="utf-8").splitlines()
                if ln.strip()]
    hand_written = [r for r in existing if not is_generated(r)]  # never touched by this script
    qs = build()
    assign_ids(qs, hand_written)
    if not args.write:
        print("\n".join(json.dumps(q) for q in qs))
        return
    rows = sorted(hand_written + qs, key=lambda r: int(r["id"][1:]))
    QUESTIONS.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                         encoding="utf-8")
    print(f"Wrote {len(hand_written)} hand-written + {len(qs)} generated questions to {QUESTIONS}")


if __name__ == "__main__":
    main()
