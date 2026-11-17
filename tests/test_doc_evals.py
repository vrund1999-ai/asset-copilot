"""Scoring for the document eval categories, and the retrieval hit-rate metric."""

import pytest

from retrieval_eval import retrieval_metrics
from run_evals import (
    date_in_answer,
    fact_matches,
    falsely_flags_discrepancy,
    flags_discrepancy,
    load_questions,
    score,
)

REF = "Lease Abstract - Acme LLC - Prop 1 Suite 2 p.2"


def resp(answer, cites=(("document", REF),), status="answered", grounded=True):
    return {"status": status, "answer": answer, "grounded": grounded,
            "citations": [{"kind": k, "reference": r} for k, r in cites]}


def lookup(**kw):
    return {"id": "x", "category": "document_lookup", "expect": "answer", "gold_refs": [REF],
            "gold_facts": [{"kind": "number", "value": 5.0}], **kw}


# ---- dates and facts -------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "It expires on 2029-03-05.", "Expiration is March 5, 2029.", "It ends Mar 5, 2029.",
    "Ends 5 March 2029.", "Ends 03/05/2029.", "Ends March 5th, 2029.",
])
def test_date_forms_are_recognised(text):
    assert date_in_answer(text, "2029-03-05")


def test_wrong_date_is_not_recognised():
    assert not date_in_answer("It expires March 6, 2029.", "2029-03-05")
    assert not date_in_answer("It expires in 2029.", "2029-03-05")


def test_fact_kinds():
    assert fact_matches("Rent is $45.67 psf.", {"kind": "number", "value": 45.67})
    assert fact_matches("Escalation is 3.00%.", {"kind": "number", "value": 0.03})
    assert not fact_matches("Escalation is 3.5%.", {"kind": "number", "value": 0.03})
    zero = {"kind": "text_any", "value": ["0", "none", "no renewal", "no option"]}
    assert fact_matches("The lease has no renewal options.", zero)
    assert not fact_matches("The lease has two renewal options.", zero)
    with pytest.raises(ValueError):
        fact_matches("x", {"kind": "bogus", "value": 1})


def test_discrepancy_flag_detection():
    assert flags_discrepancy("Discrepancy: the document says 2, the database says 1.")
    assert flags_discrepancy("The values do not match: 2 vs 1.")
    assert not flags_discrepancy("Both sources agree on 2 options.")
    assert falsely_flags_discrepancy("Discrepancy: the dates differ.")
    assert not falsely_flags_discrepancy("The document and database agree, no issues found.")


# ---- document_lookup -------------------------------------------------------------------------

def test_lookup_passes_with_fact_and_gold_citation():
    assert score(lookup(), resp("Each extension is 5 years [D1]."), None)["passed"]


@pytest.mark.parametrize("r,reason", [
    (resp("Each extension is 5 years.", cites=()), "not cited"),
    (resp("Each extension is 5 years.", cites=(("document", "Other doc p.1"),)), "not cited"),
    (resp("Each extension is 5 years.", cites=(("sql", "SELECT 1"),)), "not cited"),
    (resp("Each extension is 7 years."), "fact not found"),
    (resp("Each extension is 5 years.", grounded=False), "ungrounded"),
    (resp("I can't determine that.", status="cannot_determine"), "status="),
])
def test_lookup_failures(r, reason):
    out = score(lookup(), r, None)
    assert not out["passed"] and reason in out["reason"]


# ---- hybrid ----------------------------------------------------------------------------------

def hybrid():
    return lookup(category="hybrid", gold_sql="SELECT 1")


def test_hybrid_needs_sql_citation_and_sql_rows():
    both = resp("12,000 sq ft and 5 years.", cites=(("document", REF), ("sql", "SELECT 1")))
    assert score(hybrid(), both, [{"leased_sq_ft": 12000}])["passed"]
    out = score(hybrid(), resp("12,000 sq ft and 5 years."), [{"leased_sq_ft": 12000}])
    assert out["reason"] == "no sql citation"
    wrong = resp("13,000 sq ft and 5 years.", cites=(("document", REF), ("sql", "SELECT 1")))
    assert not score(hybrid(), wrong, [{"leased_sq_ft": 12000}])["passed"]


# ---- reconciliation --------------------------------------------------------------------------

def recon(expect_discrepancy):
    return {"id": "x", "category": "reconciliation", "expect": "answer", "gold_refs": [REF],
            "expect_discrepancy": expect_discrepancy,
            "gold_facts": [{"kind": "date", "value": "2029-02-11"},
                           {"kind": "date", "value": "2029-05-12"}]}


BOTH = (("document", REF), ("sql", "SELECT end_date FROM leases"))


def test_reconciliation_seeded_discrepancy_must_be_flagged_with_both_values():
    good = resp("Discrepancy: the document says May 12, 2029; the database says 2029-02-11.",
                cites=BOTH)
    assert score(recon(True), good, None)["passed"]
    silent = resp("The lease expires May 12, 2029 (database: 2029-02-11).", cites=BOTH)
    assert score(recon(True), silent, None)["reason"] == "seeded discrepancy not flagged"
    one_sided = resp("Discrepancy: the document says May 12, 2029.", cites=BOTH)
    assert "fact not found" in score(recon(True), one_sided, None)["reason"]


def test_reconciliation_clean_control_must_not_be_flagged():
    ctl = recon(False)
    ctl["gold_facts"] = [{"kind": "date", "value": "2029-02-11"}]
    ok = resp("It expires February 11, 2029, and the document and database agree.", cites=BOTH)
    assert score(ctl, ok, None)["passed"]
    bad = resp("Discrepancy: it expires February 11, 2029.", cites=BOTH)
    assert score(ctl, bad, None)["reason"].startswith("false discrepancy")


# ---- refusals reuse the existing path --------------------------------------------------------

def test_document_refusal_scores_on_status_only():
    q = {"id": "x", "category": "refusal", "expect": "refuse"}
    assert score(q, {"status": "cannot_determine"}, None)["passed"]
    assert not score(q, {"status": "answered"}, None)["passed"]


# ---- question file ---------------------------------------------------------------------------

def test_document_question_mix():
    qs = load_questions()
    counts = {}
    for q in qs:
        counts[q["category"]] = counts.get(q["category"], 0) + 1
    assert counts["document_lookup"] >= 8 and counts["hybrid"] >= 6
    seeded = [q for q in qs if q.get("expect_discrepancy") is True]
    controls = [q for q in qs if q.get("expect_discrepancy") is False]
    assert len(seeded) >= 5 and len(controls) >= 3


# ---- retrieval metric ------------------------------------------------------------------------

def test_retrieval_metrics_doc_vs_page_and_rank():
    qs = [
        {"id": "a", "category": "document_lookup", "question": "qa", "gold_refs": ["T1 p.2"]},
        {"id": "b", "category": "document_lookup", "question": "qb", "gold_refs": ["T2 p.1"]},
        {"id": "c", "category": "hybrid", "question": "qc", "gold_refs": ["T3 p.3"]},
    ]
    results = {
        "qa": [{"title": "T1", "page": 1}, {"title": "T1", "page": 2}],  # doc@1, page@3 only
        "qb": [{"title": "X", "page": 1}, {"title": "T2", "page": 1}],   # rank 2
        "qc": [{"title": "T3", "page": 3, "expanded": True}],           # expansions never count
    }
    m = retrieval_metrics(qs, lambda q: results[q])
    dl = m["by_category"]["document_lookup"]
    assert dl["n"] == 2 and dl["doc@1"] == 1 and dl["doc@3"] == 2
    assert dl["page@1"] == 0 and dl["page@3"] == 2
    assert m["by_category"]["hybrid"]["doc@3"] == 0
    assert m["overall"]["n"] == 3 and m["overall"]["doc@3"] == 2
