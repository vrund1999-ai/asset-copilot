import anthropic
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .governance import UnsafeQueryError
from .schemas import AskRequest, AskResponse

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
