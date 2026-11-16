import json
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from .config import settings
from .governance import MAX_ROWS, UnsafeQueryError, validate_sql


class QueryExecutionError(RuntimeError):
    """The query passed the guard but failed in Postgres (bad column, timeout, ...).

    The message is safe to show to the model so it can correct the query.
    """


@lru_cache
def admin_engine() -> Engine:
    return create_engine(settings.database_url_admin)


@lru_cache
def readonly_engine() -> Engine:
    return create_engine(settings.database_url_readonly)


def _db_message(e: SQLAlchemyError) -> str:
    """First line of the underlying driver error, without connection details."""
    orig = getattr(e, "orig", None)
    msg = str(orig) if orig is not None else str(e)
    return msg.strip().splitlines()[0] if msg.strip() else type(e).__name__


def run_readonly_query(sql: str, session_id: str | None = None) -> list[dict]:
    """Validate, execute on the read-only role, and audit-log the outcome.

    Every attempt is audited: success (`sql_query`), guard rejection (`sql_blocked`),
    and database failure (`sql_error`). At most MAX_ROWS rows are fetched.
    """
    try:
        safe_sql = validate_sql(sql)
    except UnsafeQueryError as e:
        audit("sql_blocked", {"sql": sql, "reason": str(e)}, session_id)
        raise

    try:
        with readonly_engine().connect() as conn:
            result = conn.execute(text(safe_sql))
            rows = [dict(r._mapping) for r in result.fetchmany(MAX_ROWS)]
    except SQLAlchemyError as e:
        msg = _db_message(e)
        audit("sql_error", {"sql": safe_sql, "error": msg}, session_id)
        raise QueryExecutionError(msg) from e

    audit("sql_query", {"sql": safe_sql, "row_count": len(rows)}, session_id)
    return rows


def audit(action: str, detail: dict, session_id: str | None = None) -> None:
    with admin_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO audit_log (session_id, action, detail) "
                "VALUES (:s, :a, CAST(:d AS jsonb))"
            ),
            {"s": session_id, "a": action, "d": json.dumps(detail, default=str)},
        )
