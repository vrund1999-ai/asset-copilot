from datetime import date

import anthropic
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .governance import UnsafeQueryError
from .schemas import AskRequest, AskResponse
from .variance import PortfolioSummary, VarianceReport

app = FastAPI(title="asset-copilot", version="0.1.0")


class FeedbackRequest(BaseModel):
    session_id: str | None = None
    question: str
    answer: str
    rating: int  # -1 or 1
    correction: str | None = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    from .agent import AgentConfigError, run_agent

    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="question must not be empty")
    if len(question) > 2000:
        raise HTTPException(status_code=422, detail="question must be at most 2000 characters")
    try:
        return run_agent(question, req.session_id)
    except AgentConfigError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except anthropic.RateLimitError as e:
        raise HTTPException(status_code=429, detail="The model API is rate limiting requests; "
                            "try again shortly.") from e
    except anthropic.AuthenticationError as e:
        raise HTTPException(status_code=503, detail="The model API rejected the configured key.") from e
    except anthropic.APIError as e:
        raise HTTPException(status_code=502, detail=f"Model API error: {type(e).__name__}") from e


class VarianceRequest(BaseModel):
    month: str  # "YYYY-MM" (or "YYYY-MM-DD"; the day is ignored)
    property_id: int | None = None  # None = whole portfolio
    commentary: bool = True
    session_id: str | None = None


def _parse_month(value: str) -> date:
    try:
        parts = value.strip().split("-")
        return date(int(parts[0]), int(parts[1]), 1)
    except (ValueError, IndexError) as e:
        raise HTTPException(status_code=422, detail="month must look like 2026-06") from e


@app.get("/variance/options")
def variance_options() -> dict:
    from .variance import options

    return options()


@app.get("/portfolio/summary", response_model=PortfolioSummary)
def portfolio_summary_endpoint() -> PortfolioSummary:
    """Landing-page snapshot: counts and the latest month vs budget (read-only, no model call)."""
    from .variance import ReportError, portfolio_summary

    try:
        return portfolio_summary()
    except ReportError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post("/variance", response_model=VarianceReport)
def variance(req: VarianceRequest) -> VarianceReport:
    """Budget-vs-actual report. Numbers are computed in code; commentary is checked against them."""
    from .variance import ReportError, build_report

    month = _parse_month(req.month)
    try:
        return build_report(month, req.property_id, commentary=req.commentary,
                            session_id=req.session_id)
    except ReportError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post("/query")
def query(sql: str, session_id: str | None = None) -> dict:
    """Run a guarded read-only query directly (useful for testing the governance layer)."""
    from .db import QueryExecutionError, run_readonly_query

    try:
        return {"rows": run_readonly_query(sql, session_id)}
    except UnsafeQueryError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except QueryExecutionError as e:
        raise HTTPException(status_code=400, detail=f"Query failed: {e}") from e


@app.post("/feedback")
def feedback(req: FeedbackRequest) -> dict:
    from sqlalchemy import text

    from .db import admin_engine

    if req.rating not in (-1, 1):
        raise HTTPException(status_code=422, detail="rating must be -1 or 1")
    with admin_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO feedback (session_id, question, answer, rating, correction) "
                "VALUES (:session_id, :question, :answer, :rating, :correction)"
            ),
            req.model_dump(),
        )
    return {"status": "saved"}
