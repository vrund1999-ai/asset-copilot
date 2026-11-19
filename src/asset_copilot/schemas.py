from pydantic import BaseModel, Field


class Citation(BaseModel):
    kind: str  # "sql" | "document" | "calculation"
    reference: str  # executed query text, "<doc title> p.<n>", or "<id>: <expr> = <result>"
    label: str | None = None  # e.g. "Q1", as referenced in the answer text
    excerpt: str | None = None  # document citations: the retrieved passage text (capped)


class AskRequest(BaseModel):
    question: str
    session_id: str | None = None


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    session_id: str | None = None
    status: str = "answered"  # "answered" | "cannot_determine" | "failed"
    grounded: bool = True  # every number in the answer traced to a cited result
    steps: int = 0  # model calls used
    usage: dict[str, int] = Field(default_factory=dict)
