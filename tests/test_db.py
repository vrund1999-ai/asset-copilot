"""Unit tests for db.run_readonly_query with a fake engine (no Postgres needed)."""

from contextlib import contextmanager

import pytest
from sqlalchemy.exc import ProgrammingError

from asset_copilot import db
from asset_copilot.governance import MAX_ROWS, UnsafeQueryError


class FakeResult:
    def __init__(self, n_rows):
        self.n_rows = n_rows
        self.requested = None

    def fetchmany(self, n):
        self.requested = n
        return [type("Row", (), {"_mapping": {"i": i}})() for i in range(min(n, self.n_rows))]


class FakeConn:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error

    def execute(self, _stmt):
        if self.error:
            raise self.error
        return self.result


class FakeEngine:
    def __init__(self, conn):
        self.conn = conn

    @contextmanager
    def connect(self):
        yield self.conn


@pytest.fixture
def audits(monkeypatch):
    log = []
    monkeypatch.setattr(db, "audit", lambda action, detail, session_id=None: log.append(
        (action, detail, session_id)))
    return log


def test_success_is_audited(monkeypatch, audits):
    monkeypatch.setattr(db, "readonly_engine", lambda: FakeEngine(FakeConn(FakeResult(3))))
    rows = db.run_readonly_query("SELECT 1 FROM properties", "s1")
    assert rows == [{"i": 0}, {"i": 1}, {"i": 2}]
    assert [(a, s) for a, _, s in audits] == [("sql_query", "s1")]
    assert audits[0][1]["row_count"] == 3


def test_row_cap_enforced_on_fetch(monkeypatch, audits):
    result = FakeResult(MAX_ROWS + 100)
    monkeypatch.setattr(db, "readonly_engine", lambda: FakeEngine(FakeConn(result)))
    rows = db.run_readonly_query("SELECT 1 FROM properties UNION SELECT 2 FROM tenants")
    assert result.requested == MAX_ROWS
    assert len(rows) == MAX_ROWS


def test_blocked_query_is_audited_and_never_executed(monkeypatch, audits):
    def boom():
        raise AssertionError("engine must not be touched for blocked SQL")

    monkeypatch.setattr(db, "readonly_engine", boom)
    with pytest.raises(UnsafeQueryError):
        db.run_readonly_query("DROP TABLE properties", "s2")
    action, detail, session = audits[0]
    assert (action, session) == ("sql_blocked", "s2")
    assert detail["sql"] == "DROP TABLE properties"
    assert "Only SELECT" in detail["reason"]


def test_db_error_is_wrapped_and_audited(monkeypatch, audits):
    class Orig(Exception):
        pass

    err = ProgrammingError("SELECT nope", {}, Orig('column "nope" does not exist\nLINE 1: ...'))
    monkeypatch.setattr(db, "readonly_engine", lambda: FakeEngine(FakeConn(error=err)))
    with pytest.raises(db.QueryExecutionError) as exc:
        db.run_readonly_query("SELECT nope FROM properties", "s3")
    assert str(exc.value) == 'column "nope" does not exist'
    assert [a for a, _, _ in audits] == ["sql_error"]
    assert audits[0][1]["error"] == 'column "nope" does not exist'
