"""HTTP-level tests for /ask. The agent itself is stubbed; see test_agent.py for the loop."""

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient

from asset_copilot import agent, api
from asset_copilot.schemas import AskResponse, Citation


@pytest.fixture
def client():
    return TestClient(api.app)


def _status_error(cls, status):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx.Response(status, request=req), body=None)


def test_ask_returns_agent_response(client, monkeypatch):
    seen = {}

    def fake_run(question, session_id):
        seen.update(question=question, session_id=session_id)
        return AskResponse(answer="There are 60 properties [Q1].", session_id="abc", steps=2,
                           citations=[Citation(kind="sql", reference="SELECT 1", label="Q1")])

    monkeypatch.setattr(agent, "run_agent", fake_run)
    r = client.post("/ask", json={"question": "  How many properties?  ", "session_id": "abc"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"].startswith("There are 60") and body["status"] == "answered"
    assert body["citations"] == [{"kind": "sql", "reference": "SELECT 1", "label": "Q1"}]
    assert body["grounded"] is True and body["session_id"] == "abc"
    assert seen == {"question": "How many properties?", "session_id": "abc"}


@pytest.mark.parametrize("question", ["", "   ", "x" * 2001])
def test_ask_validates_question(client, question):
    assert client.post("/ask", json={"question": question}).status_code == 422


def test_ask_without_api_key_is_503(client, monkeypatch):
    def raise_config(*_):
        raise agent.AgentConfigError("ANTHROPIC_API_KEY is not set.")

    monkeypatch.setattr(agent, "run_agent", raise_config)
    r = client.post("/ask", json={"question": "hi"})
    assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["detail"]


@pytest.mark.parametrize(
    "exc_cls,status,expected",
    [
        (anthropic.RateLimitError, 429, 429),
        (anthropic.AuthenticationError, 401, 503),
        (anthropic.InternalServerError, 500, 502),
    ],
)
def test_ask_maps_sdk_errors(client, monkeypatch, exc_cls, status, expected):
    def raise_sdk(*_):
        raise _status_error(exc_cls, status)

    monkeypatch.setattr(agent, "run_agent", raise_sdk)
    assert client.post("/ask", json={"question": "hi"}).status_code == expected


def test_ask_connection_error_is_502(client, monkeypatch):
    def raise_conn(*_):
        raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))

    monkeypatch.setattr(agent, "run_agent", raise_conn)
    assert client.post("/ask", json={"question": "hi"}).status_code == 502


def test_failed_status_is_still_http_200(client, monkeypatch):
    monkeypatch.setattr(agent, "run_agent", lambda *_: AskResponse(
        answer="I couldn't complete this within 8 steps.", status="failed", grounded=False))
    r = client.post("/ask", json={"question": "hi"})
    assert r.status_code == 200 and r.json()["status"] == "failed"


def test_portfolio_summary_endpoint(client, monkeypatch):
    from datetime import date
    from decimal import Decimal

    from asset_copilot import variance

    line = variance.line_variance("noi", Decimal(90), Decimal(100), Decimal(10), Decimal(5))
    summary = variance.PortfolioSummary(
        month=date(2026, 6, 1), n_properties=60, n_active_leases=900, n_expiring_12m=120,
        n_documents=55, totals=[line], n_flags=3, flag_pct=Decimal(10), flag_min_usd=Decimal(25000))
    monkeypatch.setattr(variance, "portfolio_summary", lambda: summary)
    r = client.get("/portfolio/summary")
    body = r.json()
    assert r.status_code == 200 and body["month"] == "2026-06-01"
    assert body["n_properties"] == 60 and body["n_flags"] == 3
    assert body["totals"][0]["variance"] == "-10.00"


def test_portfolio_summary_without_data_is_404(client, monkeypatch):
    from asset_copilot import variance

    def no_data():
        raise variance.ReportError("No months with both actuals and budget are loaded.")

    monkeypatch.setattr(variance, "portfolio_summary", no_data)
    r = client.get("/portfolio/summary")
    assert r.status_code == 404 and "No months" in r.json()["detail"]
