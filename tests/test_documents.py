import json
from datetime import date
from decimal import Decimal

import pytest

from asset_copilot.synth.documents import plan_documents, write_documents


def _leases(n=60):
    return [{
        "lease_id": i, "property_id": 1 + i // 5, "property_name": f"Prop {1 + i // 5}",
        "tenant_name": f"Tenant {i} LLC", "suite": f"Suite {i % 5 + 1}",
        "leased_sq_ft": 10_000 + i, "start_date": date(2024, 1, 1),
        "end_date": date(2030, 1, 1) + (date(2031, 1, 1) - date(2030, 1, 1)) * (i % 3),
        "base_rent_psf": Decimal("24.50"), "annual_escalation": Decimal("0.0300"),
        "renewal_options": i % 3,
    } for i in range(1, n + 1)]


def _debts(n=30):
    return [{
        "property_id": i, "property_name": f"Prop {i}", "lender": f"Lender {i} Bank",
        "principal": Decimal("12500000.00"), "rate": Decimal("0.0650"),
        "maturity_date": date(2030, 6, 30),
    } for i in range(1, n + 1)]


def test_plan_is_deterministic_for_a_seed():
    a_docs, a_disc = plan_documents(_leases(), _debts(), seed=42)
    b_docs, b_disc = plan_documents(_leases(), _debts(), seed=42)
    assert [d.text for d in a_docs] == [d.text for d in b_docs]
    assert a_disc == b_disc
    c_docs, _ = plan_documents(_leases(), _debts(), seed=43)
    assert [d.filename for d in a_docs] != [d.filename for d in c_docs]


def test_counts_and_page_structure():
    docs, disc = plan_documents(_leases(), _debts(), seed=1, n_leases=10, n_loans=4,
                                n_lease_discrepancies=3, n_loan_discrepancies=1)
    leases = [d for d in docs if d.doc_type == "lease_abstract"]
    loans = [d for d in docs if d.doc_type == "loan_summary"]
    assert (len(leases), len(loans), len(disc)) == (10, 4, 4)
    assert all(len(d.pages) == 3 for d in leases) and all(len(d.pages) == 2 for d in loans)
    assert all("<!-- page 1 -->" in d.text for d in docs)


def test_default_seeds_at_least_five_discrepancies():
    _, disc = plan_documents(_leases(), _debts(), seed=42)
    assert len(disc) >= 5
    assert {d["field"] for d in disc} >= {"end_date", "base_rent_psf", "renewal_options",
                                          "annual_escalation", "maturity_date"}


def test_discrepancy_value_is_stated_in_document_on_recorded_page():
    docs, disc = plan_documents(_leases(), _debts(), seed=42)
    by_file = {d.filename: d for d in docs}
    for item in disc:
        doc = by_file[item["file"]]
        page_text = doc.pages[item["page"] - 1]
        assert item["db_value"] != item["doc_value"]
        if item["field"] == "base_rent_psf":
            assert f"${item['doc_value']:.2f}" in page_text
        elif item["field"] == "end_date":
            d = date.fromisoformat(item["doc_value"])
            assert f"{d.strftime('%B')} {d.day}, {d.year}" in page_text


def test_non_discrepant_documents_state_database_values():
    leases = _leases()
    docs, disc = plan_documents(leases, _debts(), seed=42)
    bad = {d["file"] for d in disc}
    by_id = {r["lease_id"]: r for r in leases}
    clean = [d for d in docs if d.doc_type == "lease_abstract" and d.filename not in bad]
    assert clean
    for d in clean:
        row = by_id[d.lease_id]
        assert "$24.50 per rentable sq ft" in d.text
        assert "3.00%" in d.text
        assert f"L{row['lease_id']}" in d.text


def test_write_documents_and_manifest(tmp_path):
    docs, disc = plan_documents(_leases(), _debts(), seed=42, n_leases=5, n_loans=3,
                                n_lease_discrepancies=2, n_loan_discrepancies=1)
    path = write_documents(docs, disc, tmp_path, 42, date(2026, 6, 30))
    manifest = json.loads(path.read_text())
    assert len(manifest["documents"]) == 8 and len(manifest["discrepancies"]) == 3
    assert (tmp_path / manifest["documents"][0]["file"]).exists()
    # Re-writing removes stale files rather than accumulating them.
    write_documents(docs[:2], [], tmp_path, 42, date(2026, 6, 30))
    assert len(list(tmp_path.rglob("*.md"))) == 2


def test_more_discrepancies_than_documents_is_clamped():
    docs, disc = plan_documents(_leases(3), _debts(2), seed=1, n_leases=3, n_loans=2,
                                n_lease_discrepancies=10, n_loan_discrepancies=10)
    assert len(disc) == 5 and len(docs) == 5


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_end_date_shift_never_equals_original(seed):
    _, disc = plan_documents(_leases(), _debts(), seed=seed)
    assert all(d["db_value"] != d["doc_value"] for d in disc)
