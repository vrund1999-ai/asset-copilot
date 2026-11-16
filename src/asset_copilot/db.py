import json
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .config import settings
from .governance import validate_sql


@lru_cache
def admin_engine() -> Engine:
    return create_engine(settings.database_url_admin)


@lru_cache
def readonly_engine() -> Engine:
    return create_engine(settings.database_url_readonly)


def run_readonly_query(sql: str, session_id: str | None = None) -> list[dict]:
    """Validate, execute on the read-only role, and audit-log the query."""
    safe_sql = validate_sql(sql)
    with readonly_engine().connect() as conn:
        rows = [dict(r._mapping) for r in conn.execute(text(safe_sql))]
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
