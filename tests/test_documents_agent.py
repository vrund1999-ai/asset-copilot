"""search_documents tool, retrieval query building, and document citations in the agent loop.

No network, no database, no embedding model.
"""

import json
from types import SimpleNamespace

import pytest

from asset_copilot import agent, retrieval, tools
from asset_copilot.grounding import find_ungrounded
from asset_copilot.tools import PassageRecord, RunContext, run_search_documents
from fakes import FakeClient, response, tool_use


def hit(chunk_id, page, content, doc=1, title="Lease Abstract - Acme LLC - Prop 1 Suite 2",
        sim=0.8, expanded=False):
    return {"chunk_id": chunk_id, "document_id": doc, "title": title, "doc_type": "lease_abstract",
            "property_id": 1, "page": page, "content": content, "similarity": sim,
            "expanded": expanded}


RENEWAL = hit(11, 2, "## Renewal Options\n\n2 option(s) to extend the term for 5 years each at 95% "
                     "of fair market rent, exercisable on 9 months written notice.")
TERM = hit(10, 1, "- Expiration Date: March 25, 2029", expanded=True)


@pytest.fixture
def search_stub(monkeypatch):
    state = SimpleNamespace(rows=[RENEWAL, TERM], calls=[], fail=None)

    def fake(query, **kw):
        state.calls.append({"query": query, **kw})
        if state.fail:
            raise state.fail
        return list(state.rows)

    monkeypatch.setattr(retrieval, "search", fake)
    return state


# ---- tool handler ----------------------------------------------------------------------------

def test_search_assigns_passage_ids_and_passes_filters(search_stub):
    ctx = RunContext("s")
    out = run_search_documents(ctx, {"query": " renewal options ", "document_id": 7, "top_k": 99})
    assert not out.is_error
    assert [p["passage_id"] for p in out.payload["passages"]] == ["D1", "D2"]
    assert out.payload["passages"][0]["matched_query"] is True
    assert out.payload["passages"][1]["matched_query"] is False
    assert search_stub.calls == [{"query": "renewal options", "top_k": 8, "property_id": None,
                                  "document_id": 7, "doc_type": None}]
    assert ctx.passages["D1"].page == 2 and ctx.passages["D1"].title.startswith("Lease Abstract")
    assert out.audit["passage_ids"] == ["D1", "D2"] and out.audit["filters"] == {"document_id": 7}


def test_repeat_search_reuses_passage_ids(search_stub):
    ctx = RunContext("s")
    run_search_documents(ctx, {"query": "a"})
    out = run_search_documents(ctx, {"query": "b"})
    assert [p["passage_id"] for p in out.payload["passages"]] == ["D1", "D2"]
    assert len(ctx.passages) == 2


@pytest.mark.parametrize("args", [
    {}, {"query": ""}, {"query": "x" * 501}, {"query": "x", "doc_type": "memo"},
    {"query": "x", "property_id": "1"}, {"query": "x", "document_id": True},
])
def test_search_rejects_bad_input_without_calling_search(search_stub, args):
    out = run_search_documents(RunContext("s"), args)
    assert out.is_error and search_stub.calls == []


def test_search_failure_is_returned_to_the_model_not_raised(search_stub):
    search_stub.fail = RuntimeError("sentence-transformers is not installed")
    out = run_search_documents(RunContext("s"), {"query": "x"})
    assert out.is_error and "unavailable" in out.payload["error"]
    assert "sentence-transformers" not in json.dumps(out.payload)  # internals stay in the audit


def test_search_no_results_note(search_stub):
    search_stub.rows = []
    out = run_search_documents(RunContext("s"), {"query": "x"})
    assert not out.is_error and out.payload["count"] == 0 and "note" in out.payload


# ---- retrieval query building ----------------------------------------------------------------

class FakeConn:
    def __init__(self, batches, log):
        self.batches, self.log = list(batches), log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, stmt, params):
        self.log.append((str(stmt), dict(params)))
        return [SimpleNamespace(_mapping=r) for r in self.batches.pop(0)]


def test_retrieval_filters_and_expands_best_document(monkeypatch):
    log = []
    hits = [{"chunk_id": 5, "document_id": 3, "page": 2},
            {"chunk_id": 9, "document_id": 4, "page": 1}]
    extras = [{"chunk_id": 6, "document_id": 3, "page": 3}]
    monkeypatch.setattr(retrieval, "_embedder",
                        lambda: SimpleNamespace(embed=lambda t: [[0.5, 0.5]]))
    monkeypatch.setattr(retrieval, "readonly_engine",
                        lambda: SimpleNamespace(connect=lambda: FakeConn([hits, extras], log)))
    rows = retrieval.search("renewal", property_id=2, doc_type="lease_abstract", top_k=2)

    sql1, p1 = log[0]
    assert "d.property_id = :property_id" in sql1 and "d.doc_type = :doc_type" in sql1
    assert "document_id = :document_id" not in sql1 and p1["k"] == 2
    assert p1["v"] == "[0.500000,0.500000]"
    sql2, p2 = log[1]
    assert p2["doc"] == 3 and p2["seen"] == [5, 9] and "<> ALL(:seen)" in sql2
    assert [(r["chunk_id"], r["expanded"]) for r in rows] == [(5, False), (9, False), (6, True)]


def test_retrieval_no_hits_skips_expansion(monkeypatch):
    log = []
    monkeypatch.setattr(retrieval, "_embedder", lambda: SimpleNamespace(embed=lambda t: [[1.0]]))
    monkeypatch.setattr(retrieval, "readonly_engine",
                        lambda: SimpleNamespace(connect=lambda: FakeConn([[]], log)))
    assert retrieval.search("x") == [] and len(log) == 1


# ---- grounding with passages -----------------------------------------------------------------

P = PassageRecord("D1", 11, 1, "T", 2, RENEWAL["content"])


def test_numbers_in_cited_passage_and_page_are_grounded():
    ans = "Tenant has 2 options of 5 years at 95% of market, 9 months notice (page 2) [D1]."
    assert find_ungrounded(ans, "q", [], [], [P]) == []


def test_number_not_in_passage_is_ungrounded_and_uncited_passage_does_not_count():
    assert find_ungrounded("There are 3 options.", "q", [], [], [P]) == ["3"]
    assert find_ungrounded("There are 2 options.", "q", [], [], []) == ["2"]


# ---- agent loop ------------------------------------------------------------------------------

def search(id_="d1", query="renewal options", **kw):
    return tool_use(id_, "search_documents", query=query, **kw)


def submit_doc(answer, doc_ids=("D1",), query_ids=(), id_="s1", status="answered"):
    return tool_use(id_, "submit_answer", status=status, answer=answer,
                    doc_ids=list(doc_ids), query_ids=list(query_ids), calc_ids=[])


def run(client):
    return agent.run_agent("What are the renewal options for Acme LLC?", "sess-d", client=client)


def last_error(client, call_index):
    content = client.calls[call_index]["messages"][-1]["content"][0]["content"]
    return json.loads(content)["error"]


def test_document_only_answer_has_document_citation(search_stub, fake_db, audit_log):
    client = FakeClient(
        response(search()),
        response(submit_doc("Acme has 2 renewal options of 5 years each [D1].")),
    )
    out = run(client)
    assert out.status == "answered" and out.grounded
    assert [(c.kind, c.label, c.reference) for c in out.citations] == [
        ("document", "D1", "Lease Abstract - Acme LLC - Prop 1 Suite 2 p.2")]
    actions = [e["action"] for e in audit_log]
    assert actions.count("tool_call") == 2 and "answer_final" in actions
    call = next(e for e in audit_log if e["detail"].get("tool") == "search_documents")
    assert call["detail"]["passage_ids"] == ["D1", "D2"]


def test_hybrid_answer_carries_sql_and_document_citations(search_stub, fake_db, audit_log):
    fake_db.rows = [{"renewal_options": 2}]
    client = FakeClient(
        response(tool_use("t1", "run_sql", sql="SELECT renewal_options FROM leases", purpose="x")),
        response(search()),
        response(submit_doc("Database and document agree: 2 options [Q1][D1].", query_ids=["Q1"])),
    )
    out = run(client)
    assert [c.kind for c in out.citations] == ["sql", "document"] and out.grounded


def test_fabricated_doc_id_is_rejected_then_recovered(search_stub, fake_db, audit_log):
    client = FakeClient(
        response(search()),
        response(submit_doc("2 options [D9].", doc_ids=["D9"])),
        response(submit_doc("2 options [D1].", id_="s2")),
    )
    out = run(client)
    assert out.status == "answered" and out.steps == 3
    err = last_error(client, 2)
    assert "D9" in err and "D1" in err


def test_answered_without_any_citation_is_rejected(fake_db, audit_log):
    client = FakeClient(
        response(submit_doc("Probably 2.", doc_ids=[])),
        response(submit_doc("cannot", doc_ids=[], status="cannot_determine", id_="s2")),
    )
    out = run(client)
    assert out.status == "cannot_determine"
    err = last_error(client, 1)
    assert "at least one query_id" in err and "doc_id" in err


def test_number_missing_from_passage_triggers_correction_then_ungrounded(search_stub, fake_db,
                                                                         audit_log):
    client = FakeClient(
        response(search()),
        response(submit_doc("Acme has 4 renewal options [D1].")),
        response(submit_doc("Acme has 4 renewal options [D1].", id_="s2")),
    )
    out = run(client)
    assert out.status == "answered" and out.grounded is False


def test_search_failure_lets_model_refuse(search_stub, fake_db, audit_log):
    search_stub.fail = RuntimeError("boom")
    client = FakeClient(
        response(search()),
        response(submit_doc("Document search is down.", doc_ids=[], status="cannot_determine")),
    )
    out = run(client)
    assert out.status == "cannot_determine"
    kinds = [e["detail"].get("kind") for e in audit_log if e["action"] == "tool_call"]
    assert kinds[0] == "search_failed"


def test_tool_schema_declares_search_and_doc_ids():
    names = {t["name"]: t for t in tools.TOOLS}
    assert "search_documents" in names
    assert "doc_ids" in names["submit_answer"]["input_schema"]["properties"]


def test_document_citation_carries_the_passage_text(search_stub, fake_db, audit_log):
    client = FakeClient(
        response(search()),
        response(submit_doc("Acme has 2 renewal options of 5 years each [D1].")),
    )
    out = run(client)
    cite = out.citations[0]
    assert cite.excerpt == RENEWAL["content"].strip()
    assert "9 months written notice" in cite.excerpt


def test_long_passage_excerpt_is_trimmed(search_stub, fake_db, audit_log):
    from asset_copilot.agent import EXCERPT_MAX_CHARS, _excerpt

    assert _excerpt("short  \n") == "short"
    long = _excerpt("x" * (EXCERPT_MAX_CHARS + 500))
    assert len(long) == EXCERPT_MAX_CHARS + 3 and long.endswith("...")


def test_sql_citation_has_no_excerpt(search_stub, fake_db, audit_log):
    fake_db.rows = [{"renewal_options": 2}]
    client = FakeClient(
        response(tool_use("t1", "run_sql", sql="SELECT renewal_options FROM leases", purpose="x")),
        response(search()),
        response(submit_doc("2 options [Q1][D1].", query_ids=["Q1"])),
    )
    out = run(client)
    assert out.citations[0].kind == "sql" and out.citations[0].excerpt is None
    assert out.citations[1].excerpt
