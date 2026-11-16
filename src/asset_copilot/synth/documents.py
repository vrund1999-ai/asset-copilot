"""Synthetic lease abstracts and loan summaries, consistent with the database.

Usage:  python -m asset_copilot.synth.documents --seed 42   (after generating the portfolio)

Each document is built from the real `leases` / `debt` rows, so retrieval answers agree with SQL
answers, EXCEPT for a deliberate, seeded set of discrepancies (a wrong end date, rent, renewal
count, escalation, loan maturity or rate). `manifest.json` records every document and every
discrepancy; it is the ground truth for reconciliation tests and evals. Output goes to
`data/generated/` (gitignored). Fully synthetic; same seed and DB give identical files.

Pages are marked with `<!-- page N -->` so ingestion can keep page numbers for citations.
"""

import argparse
import json
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text

from ..config import settings
from ..db import admin_engine

LEASE_FIELDS = ["end_date", "base_rent_psf", "renewal_options", "annual_escalation"]
DEBT_FIELDS = ["maturity_date", "rate"]

LEASE_BOILERPLATE = [
    ("Use", (
        "The Premises shall be used solely for general office, warehouse or retail use "
        "consistent with the building's zoning and certificate of occupancy.")),
    ("Insurance", (
        "Tenant shall maintain commercial general liability coverage of not less than "
        "$2,000,000 per occurrence and name Landlord as additional insured.")),
    ("Assignment", (
        "Tenant may not assign or sublet without Landlord's prior written consent, "
        "not to be unreasonably withheld for an affiliate.")),
    ("Operating Expenses", (
        "Tenant pays its pro rata share of operating expenses, taxes and "
        "insurance on a triple-net basis, reconciled annually.")),
    ("SNDA", (
        "Tenant shall execute a customary subordination, non-disturbance and attornment "
        "agreement within 15 business days of request.")),
    ("Default", (
        "Monetary default continues for 5 days after written notice; non-monetary "
        "default for 30 days, extended while cure is diligently pursued.")),
    ("Holdover", (
        "Holdover rent is 150% of the rent in effect for the first 60 days and 200% "
        "thereafter.")),
]
LOAN_BOILERPLATE = [
    ("Prepayment", (
        "Prepayment is permitted with 30 days' notice subject to yield maintenance "
        "for the first 24 months and 1% thereafter.")),
    ("Reporting", (
        "Borrower delivers quarterly operating statements within 45 days of quarter "
        "end and audited annual statements within 120 days.")),
    ("Reserves", (
        "Borrower funds monthly tax and insurance escrows and a replacement reserve.")),
    ("Recourse", (
        "The loan is non-recourse subject to customary carve-outs for fraud, "
        "misapplication of funds and voluntary bankruptcy.")),
]


@dataclass
class Doc:
    filename: str  # relative to the output dir, e.g. leases/lease_00012.md
    doc_type: str  # lease_abstract | loan_summary
    title: str
    property_id: int
    lease_id: int | None
    pages: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(f"<!-- page {i} -->\n{p}" for i, p in enumerate(self.pages, 1))


def _long_date(d: date) -> str:
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def _pct(x) -> str:
    return f"{float(x) * 100:.2f}%"


def _money(x) -> str:
    return f"${float(x):,.2f}"


def _renewal_text(n: int) -> str:
    if n == 0:
        return "None. Tenant has no right to extend the term."
    return (f"{n} option(s) to extend the term for 5 years each at 95% of fair market rent, "
            "exercisable on 9 months' written notice.")


def _shift(d: date, months: int) -> date:
    return d + timedelta(days=30 * months)


def _lease_pages(row: dict, v: dict, rnd: random.Random) -> list[str]:
    """`v` holds the values stated in the document (== DB values unless a discrepancy is seeded)."""
    p1 = (
        f"# Lease Abstract: {row['tenant_name']}\n\n"
        f"**Lease ID:** L{row['lease_id']}\n"
        f"**Property:** {row['property_name']}\n"
        f"**Tenant:** {row['tenant_name']}\n"
        f"**Premises:** {row['suite']}, {row['leased_sq_ft']:,} rentable sq ft\n\n"
        "## Term\n\n"
        f"- Commencement Date: {_long_date(row['start_date'])}\n"
        f"- Expiration Date: {_long_date(v['end_date'])}\n"
    )
    p2 = (
        "## Rent\n\n"
        f"- Base Rent: ${float(v['base_rent_psf']):.2f} per rentable sq ft per year\n"
        f"- Annual Escalation: {_pct(v['annual_escalation'])} on each anniversary of the "
        "Commencement Date\n\n"
        "## Renewal Options\n\n"
        f"{_renewal_text(v['renewal_options'])}\n"
    )
    clauses = rnd.sample(LEASE_BOILERPLATE, 4)
    p3 = "## Other Provisions\n\n" + "\n\n".join(f"**{h}.** {b}" for h, b in clauses) + "\n"
    return [p1, p2, p3]


def _loan_pages(row: dict, v: dict, rnd: random.Random) -> list[str]:
    p1 = (
        f"# Loan Summary: {row['property_name']}\n\n"
        f"**Property:** {row['property_name']}\n"
        f"**Lender:** {row['lender']}\n\n"
        "## Key Terms\n\n"
        f"- Original Principal: {_money(row['principal'])}\n"
        f"- Interest Rate: {_pct(v['rate'])} per annum\n"
        f"- Maturity Date: {_long_date(v['maturity_date'])}\n"
    )
    clauses = rnd.sample(LOAN_BOILERPLATE, 3)
    p2 = "## Covenants and Other Terms\n\n" + "\n\n".join(f"**{h}.** {b}" for h, b in clauses) + "\n"
    return [p1, p2]


def _lease_mutation(row: dict, fld: str, rnd: random.Random) -> tuple[object, object]:
    """Return (db_value, wrong_doc_value) for a seeded lease discrepancy."""
    if fld == "end_date":
        return row["end_date"], _shift(row["end_date"], rnd.choice([-9, -6, -3, 3, 6, 9]))
    if fld == "base_rent_psf":
        db = Decimal(row["base_rent_psf"])
        factor = 1 + rnd.choice([-1, 1]) * rnd.uniform(0.08, 0.15)
        return db, Decimal(str(round(float(db) * factor, 2)))
    if fld == "renewal_options":
        return row["renewal_options"], rnd.choice(
            [n for n in range(4) if n != row["renewal_options"]])
    db = Decimal(row["annual_escalation"])
    return db, Decimal(str(rnd.choice([x for x in (0.02, 0.025, 0.03, 0.035, 0.04)
                                       if abs(x - float(db)) > 1e-9])))


def _debt_mutation(row: dict, fld: str, rnd: random.Random) -> tuple[object, object]:
    if fld == "maturity_date":
        return row["maturity_date"], _shift(row["maturity_date"], rnd.choice([-12, -6, 6, 12]))
    db = Decimal(row["rate"])
    delta = Decimal(str(rnd.choice([-1, 1]) * rnd.choice([0.0025, 0.005, 0.0075])))
    return db, db + delta


def _jsonable(x):
    return x.isoformat() if isinstance(x, date) else float(x) if isinstance(x, Decimal) else x


def plan_documents(
    leases: list[dict], debts: list[dict], seed: int, n_leases: int = 40, n_loans: int = 15,
    n_lease_discrepancies: int = 6, n_loan_discrepancies: int = 2,
) -> tuple[list[Doc], list[dict]]:
    """Pure function: DB rows in, documents and the discrepancy ground truth out."""
    rnd = random.Random(seed)
    leases = sorted(leases, key=lambda r: r["lease_id"])
    debts = sorted(debts, key=lambda r: r["property_id"])
    chosen_leases = sorted(rnd.sample(leases, min(n_leases, len(leases))),
                           key=lambda r: r["lease_id"])
    chosen_debts = sorted(rnd.sample(debts, min(n_loans, len(debts))),
                          key=lambda r: r["property_id"])
    lease_bad = dict(zip(
        rnd.sample(range(len(chosen_leases)), min(n_lease_discrepancies, len(chosen_leases))),
        LEASE_FIELDS * 10))
    debt_bad = dict(zip(
        rnd.sample(range(len(chosen_debts)), min(n_loan_discrepancies, len(chosen_debts))),
        DEBT_FIELDS * 10))

    docs: list[Doc] = []
    discrepancies: list[dict] = []

    for i, row in enumerate(chosen_leases):
        stated = {f: row[f] for f in LEASE_FIELDS}
        if i in lease_bad:
            fld = lease_bad[i]
            db_val, wrong = _lease_mutation(row, fld, rnd)
            stated[fld] = wrong
            discrepancies.append({
                "file": f"leases/lease_{row['lease_id']:05d}.md", "doc_type": "lease_abstract",
                "entity": "lease", "entity_id": row["lease_id"], "field": fld,
                "db_value": _jsonable(db_val), "doc_value": _jsonable(wrong), "page": 1 if
                fld == "end_date" else 2,
            })
        docs.append(Doc(
            filename=f"leases/lease_{row['lease_id']:05d}.md", doc_type="lease_abstract",
            title=f"Lease Abstract - {row['tenant_name']} - {row['property_name']} "
                  f"{row['suite']}",
            property_id=row["property_id"], lease_id=row["lease_id"],
            pages=_lease_pages(row, stated, rnd)))

    for i, row in enumerate(chosen_debts):
        stated = {f: row[f] for f in DEBT_FIELDS}
        if i in debt_bad:
            fld = debt_bad[i]
            db_val, wrong = _debt_mutation(row, fld, rnd)
            stated[fld] = wrong
            discrepancies.append({
                "file": f"loans/loan_p{row['property_id']:03d}.md", "doc_type": "loan_summary",
                "entity": "debt", "entity_id": row["property_id"], "field": fld,
                "db_value": _jsonable(db_val), "doc_value": _jsonable(wrong), "page": 1,
            })
        docs.append(Doc(
            filename=f"loans/loan_p{row['property_id']:03d}.md", doc_type="loan_summary",
            title=f"Loan Summary - {row['property_name']}", property_id=row["property_id"],
            lease_id=None, pages=_loan_pages(row, stated, rnd)))

    return docs, discrepancies


def write_documents(docs: list[Doc], discrepancies: list[dict], out_dir: Path, seed: int,
                    as_of: date) -> Path:
    for sub in ("leases", "loans"):
        d = out_dir / sub
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob("*.md"):
            old.unlink()
    for doc in docs:
        (out_dir / doc.filename).write_text(doc.text, encoding="utf-8")
    manifest = {
        "seed": seed, "as_of": as_of.isoformat(),
        "documents": [{"file": d.filename, "doc_type": d.doc_type, "title": d.title,
                       "property_id": d.property_id, "lease_id": d.lease_id,
                       "pages": len(d.pages)} for d in docs],
        "discrepancies": discrepancies,
    }
    path = out_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def _load_rows() -> tuple[list[dict], list[dict]]:
    with admin_engine().connect() as conn:
        leases = [dict(r._mapping) for r in conn.execute(text(
            "SELECT l.lease_id, l.property_id, p.name AS property_name, t.name AS tenant_name, "
            "l.suite, l.leased_sq_ft, l.start_date, l.end_date, l.base_rent_psf, "
            "l.annual_escalation, l.renewal_options FROM leases l "
            "JOIN properties p USING (property_id) JOIN tenants t USING (tenant_id) "
            "WHERE p.asset_type <> 'multifamily'"))]
        debts = [dict(r._mapping) for r in conn.execute(text(
            "SELECT d.property_id, p.name AS property_name, d.lender, d.principal, d.rate, "
            "d.maturity_date FROM debt d JOIN properties p USING (property_id)"))]
    return leases, debts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--leases", type=int, default=40)
    ap.add_argument("--loans", type=int, default=15)
    ap.add_argument("--lease-discrepancies", type=int, default=6)
    ap.add_argument("--loan-discrepancies", type=int, default=2)
    ap.add_argument("--out", type=Path, default=Path(settings.generated_dir))
    args = ap.parse_args()
    leases, debts = _load_rows()
    docs, disc = plan_documents(leases, debts, args.seed, args.leases, args.loans,
                                args.lease_discrepancies, args.loan_discrepancies)
    path = write_documents(docs, disc, args.out, args.seed, settings.as_of_date)
    print(f"Wrote {len(docs)} documents and {len(disc)} seeded discrepancies. Manifest: {path}")


if __name__ == "__main__":
    main()
