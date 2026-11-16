from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .governance import UnsafeQueryError

app = FastAPI(title="asset-copilot", version="0.1.0")


class AskRequest(BaseModel):
    question: str
    session_id: str | None = None


class Citation(BaseModel):
    kind: str  # "sql" | "document"
    reference: str  # the query text, or "doc title p.N"


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation] = []


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
    # TODO(week 2): wire up the agent loop in agent.py
    raise HTTPException(status_code=501, detail="Agent not implemented yet")


@app.post("/query")
def query(sql: str, session_id: str | None = None) -> dict:
    """Run a guarded read-only query directly (useful for testing the governance layer)."""
    from .db import run_readonly_query

    try:
        return {"rows": run_readonly_query(sql, session_id)}
    except UnsafeQueryError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


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
