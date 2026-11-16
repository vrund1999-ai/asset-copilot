"""Tool schemas and handlers for the agent: run_sql and calculate.

submit_answer is declared here but handled in agent.py because it needs the whole run context.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from . import db
from .calc import CalcError, calculate
from .config import settings
from .governance import MAX_ROWS, UnsafeQueryError

TOOLS: list[dict[str, Any]] = [
    {
        "name": "run_sql",
        "description": (
            "Run ONE read-only PostgreSQL SELECT against the portfolio database. Returns columns, "
            "rows (the first rows only if large) and a query_id (Q1, Q2, ...) you can cite. "
            "Errors are returned so you can fix the query and retry."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "A single SELECT statement."},
                "purpose": {"type": "string", "description": "One short line: what this answers."},
            },
            "required": ["sql"],
        },
    },
    {
        "name": "calculate",
        "description": (
            "Exact arithmetic. Use for ANY derived number (ratios, percentages, differences, sums) "
            "that SQL did not already return. Supports + - * / // % **, parentheses, "
            "round(), abs(), min(), max(). Returns a calc_id (C1, C2, ...) you can cite."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "e.g. (1250000 - 1100000) / 1100000 * 100"},
                "label": {"type": "string", "description": "What the result represents."},
            },
            "required": ["expression"],
        },
    },
    {
        "name": "submit_answer",
        "description": (
            "Finish. Call this alone (not alongside other tools) once you have what you need. "
            "status 'answered' requires at least one query_id. Use 'cannot_determine' when the "
            "data cannot answer the question."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["answered", "cannot_determine"]},
                "answer": {"type": "string", "description": "The answer, with inline [Q1]-style references."},
                "query_ids": {"type": "array", "items": {"type": "string"}},
                "calc_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["status", "answer"],
        },
    },
]


@dataclass
class QueryRecord:
    id: str
    sql: str  # the SQL that actually executed (guard applied)
    purpose: str
    columns: list[str]
    rows: list[dict]  # raw values, capped at MAX_ROWS


@dataclass
class CalcRecord:
    id: str
    expression: str
    label: str
    result: Decimal


@dataclass
class RunContext:
    session_id: str
    queries: dict[str, QueryRecord] = field(default_factory=dict)
    calcs: dict[str, CalcRecord] = field(default_factory=dict)
    sql_errors: int = 0
    corrections: int = 0


@dataclass
class ToolOutcome:
    payload: dict[str, Any]
    is_error: bool = False
    audit: dict[str, Any] = field(default_factory=dict)


def jsonable(v: Any) -> Any:
    """Make DB values JSON-safe without losing precision (Decimals become strings)."""
    if isinstance(v, Decimal):
        return format(v, "f")
    if isinstance(v, date | datetime):
        return v.isoformat()
    return v


def format_decimal(d: Decimal) -> str:
    """Plain notation without trailing zeros or exponents (42000.000 -> '42000'), max 10 decimals."""
    if d.as_tuple().exponent < -10:  # type: ignore[operator]
        d = round(d, 10)
    return format(d.normalize(), "f")


def run_sql(ctx: RunContext, args: dict) -> ToolOutcome:
    sql = args.get("sql")
    if not isinstance(sql, str) or not sql.strip():
        ctx.sql_errors += 1
        return ToolOutcome({"error": "sql must be a non-empty string"}, True, {"error": "bad input"})
    purpose = str(args.get("purpose") or "")

    try:
        executed_sql, rows = db.run_readonly_query_full(sql, ctx.session_id)
    except UnsafeQueryError as e:
        ctx.sql_errors += 1
        return ToolOutcome(
            {"error": f"Query blocked by policy: {e}",
             "hint": "Only a single SELECT on the documented tables is allowed."},
            True, {"error": str(e), "kind": "blocked"},
        )
    except db.QueryExecutionError as e:
        ctx.sql_errors += 1
        return ToolOutcome(
            {"error": f"Query failed in Postgres: {e}", "hint": "Check column and table names."},
            True, {"error": str(e), "kind": "db_error"},
        )

    qid = f"Q{len(ctx.queries) + 1}"
    columns = list(rows[0].keys()) if rows else []
    ctx.queries[qid] = QueryRecord(qid, executed_sql, purpose, columns, rows)

    shown = rows[: settings.max_result_rows_to_model]
    payload: dict[str, Any] = {
        "query_id": qid,
        "columns": columns,
        "rows": [{k: jsonable(v) for k, v in r.items()} for r in shown],
        "row_count": len(rows),
        "rows_shown": len(shown),
    }
    if len(rows) > len(shown):
        payload["note"] = f"Only the first {len(shown)} of {len(rows)} rows are shown."
    if len(rows) >= MAX_ROWS:
        payload["warning"] = (
            f"Result hit the {MAX_ROWS}-row cap and may be incomplete. Aggregate in SQL instead."
        )
    return ToolOutcome(payload, False, {"query_id": qid, "row_count": len(rows)})


def run_calculate(ctx: RunContext, args: dict) -> ToolOutcome:
    expression = args.get("expression")
    try:
        result = calculate(expression)  # type: ignore[arg-type]
    except CalcError as e:
        return ToolOutcome({"error": str(e)}, True, {"error": str(e)})
    cid = f"C{len(ctx.calcs) + 1}"
    ctx.calcs[cid] = CalcRecord(cid, expression, str(args.get("label") or ""), result)
    text = format_decimal(result)
    return ToolOutcome(
        {"calc_id": cid, "expression": expression, "result": text},
        False, {"calc_id": cid, "result": text},
    )
