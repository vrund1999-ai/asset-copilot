import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent))  # lets tests import `fakes`

from asset_copilot import db
from asset_copilot.governance import validate_sql


@pytest.fixture(scope="session")
def live_db():
    """Skip (not fail) when no Postgres with the synthetic portfolio is reachable, e.g. in CI."""
    from sqlalchemy import text

    try:
        with db.admin_engine().connect() as conn:
            if not conn.execute(text("SELECT count(*) FROM operating_statements")).scalar():
                pytest.skip("database has no synthetic data (run synth.generate)")
    except Exception as e:  # noqa: BLE001 - any connection problem means "no DB here"
        pytest.skip(f"no database available: {type(e).__name__}")
    return db.admin_engine()


@pytest.fixture
def audit_log(monkeypatch):
    """Capture audit() calls instead of writing to Postgres."""
    log = []
    monkeypatch.setattr(db, "audit", lambda action, detail, session_id=None: log.append(
        {"action": action, "detail": detail, "session_id": session_id}))
    return log


@pytest.fixture
def fake_db(monkeypatch):
    """Replace query execution. Runs the REAL guard, then returns canned rows.

    Usage: fake_db.rows = [{"n": 60}]; fake_db.fail_with = QueryExecutionError("...")
    """

    state = SimpleNamespace(rows=[{"n": 60}], fail_with=None, executed=[])

    def run_full(sql, session_id=None):
        safe = validate_sql(sql)  # raises UnsafeQueryError exactly like production
        if state.fail_with is not None:
            raise state.fail_with
        state.executed.append(safe)
        return safe, list(state.rows)

    monkeypatch.setattr(db, "run_readonly_query_full", run_full)
    return state
