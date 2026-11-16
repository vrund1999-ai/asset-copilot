import json
import math
from datetime import date
from pathlib import Path

from asset_copilot.config import settings
from asset_copilot.embeddings import HashEmbedder
from asset_copilot.ingest import build_rows, chunk_page, parse_pages
from asset_copilot.synth.documents import plan_documents, write_documents


def test_parse_pages_keeps_page_numbers():
    raw = "<!-- page 1 -->\nAlpha\n\n<!-- page 2 -->\nBeta\n\n<!-- page 3 -->\nGamma"
    assert parse_pages(raw) == [(1, "Alpha"), (2, "Beta"), (3, "Gamma")]


def test_parse_pages_without_markers_is_single_page_and_empty_is_empty():
    assert parse_pages("just text") == [(1, "just text")]
    assert parse_pages("   \n") == []


def test_chunk_page_packs_paragraphs_and_respects_bound():
    para = "word " * 60  # ~300 chars
    chunks = chunk_page("\n\n".join([para] * 5), max_chars=700)
    assert len(chunks) == 3 and all(len(c) <= 700 for c in chunks)


def test_chunk_page_splits_oversize_paragraph():
    chunks = chunk_page("word " * 1000, max_chars=500)
    assert len(chunks) > 5 and all(len(c) <= 500 for c in chunks)
    assert "".join(chunks).replace(" ", "") == ("word" * 1000)


def test_hash_embedder_dim_norm_determinism_and_similarity():
    e = HashEmbedder()
    a, b, c = e.embed(["renewal option five years", "renewal option five years notice",
                       "loan prepayment yield maintenance"])
    assert len(a) == settings.embedding_dim
    assert math.isclose(sum(x * x for x in a), 1.0, rel_tol=1e-9)
    assert e.embed(["renewal option five years"])[0] == a
    dot = lambda u, v: sum(x * y for x, y in zip(u, v, strict=True))
    assert dot(a, b) > dot(a, c)


def test_build_rows_end_to_end_with_page_numbers(tmp_path: Path):
    leases = [{
        "lease_id": 7, "property_id": 1, "property_name": "Prop 1", "tenant_name": "Acme LLC",
        "suite": "Suite 1", "leased_sq_ft": 12_000, "start_date": date(2024, 1, 1),
        "end_date": date(2030, 1, 1), "base_rent_psf": 25, "annual_escalation": 0.03,
        "renewal_options": 2}]
    docs, disc = plan_documents(leases, [], seed=1, n_leases=1, n_loans=0,
                                n_lease_discrepancies=0, n_loan_discrepancies=0)
    write_documents(docs, disc, tmp_path, 1, date(2026, 6, 30))
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    rows = build_rows(manifest, tmp_path, HashEmbedder())
    assert len(rows) == 1 and rows[0]["lease_id"] == 7
    chunks = rows[0]["chunks"]
    assert {c["page"] for c in chunks} == {1, 2, 3}
    assert all(len(c["embedding"]) == settings.embedding_dim for c in chunks)
    assert any("Expiration Date" in c["content"] and c["page"] == 1 for c in chunks)
    assert any("Renewal Options" in c["content"] and c["page"] == 2 for c in chunks)
