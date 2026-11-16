from datetime import date
from decimal import Decimal

from asset_copilot.config import settings
from asset_copilot.db import QueryExecutionError
from asset_copilot.governance import MAX_ROWS
from asset_copilot.tools import RunContext, jsonable, run_calculate, run_sql


def test_run_sql_success_assigns_ids_and_stores_full_rows(fake_db):
    fake_db.rows = [{"n": 60}]
    ctx = RunContext("s")
    out = run_sql(ctx, {"sql": "SELECT COUNT(*) AS n FROM properties", "purpose": "count"})
    assert not out.is_error
    assert out.payload["query_id"] == "Q1" and out.payload["rows"] == [{"n": 60}]
    assert ctx.queries["Q1"].sql.endswith("LIMIT 500")  # the executed SQL, guard applied
    assert run_sql(ctx, {"sql": "SELECT 1 FROM tenants"}).payload["query_id"] == "Q2"


def test_rows_truncated_for_model_but_kept_server_side(fake_db):
    fake_db.rows = [{"i": i} for i in range(200)]
    ctx = RunContext("s")
    out = run_sql(ctx, {"sql": "SELECT i FROM tenants"})
    assert out.payload["rows_shown"] == settings.max_result_rows_to_model
    assert out.payload["row_count"] == 200 and "note" in out.payload
    assert len(ctx.queries["Q1"].rows) == 200


def test_cap_warning(fake_db):
    fake_db.rows = [{"i": i} for i in range(MAX_ROWS)]
    out = run_sql(RunContext("s"), {"sql": "SELECT i FROM tenants"})
    assert "may be incomplete" in out.payload["warning"]


def test_decimals_and_dates_serialized_without_precision_loss(fake_db):
    fake_db.rows = [{"v": Decimal("1234.50"), "d": date(2026, 6, 1)}]
    out = run_sql(RunContext("s"), {"sql": "SELECT 1 FROM properties"})
    assert out.payload["rows"] == [{"v": "1234.50", "d": "2026-06-01"}]
    assert jsonable(Decimal("1E+3")) == "1000"


def test_blocked_sql_is_an_error_result_and_counts(fake_db):
    ctx = RunContext("s")
    out = run_sql(ctx, {"sql": "DROP TABLE leases"})
    assert out.is_error and "blocked by policy" in out.payload["error"]
    assert ctx.sql_errors == 1 and not ctx.queries and not fake_db.executed


def test_db_error_is_an_error_result(fake_db):
    fake_db.fail_with = QueryExecutionError('column "nope" does not exist')
    ctx = RunContext("s")
    out = run_sql(ctx, {"sql": "SELECT nope FROM properties"})
    assert out.is_error and 'column "nope" does not exist' in out.payload["error"]
    assert ctx.sql_errors == 1


def test_bad_input(fake_db):
    for args in ({}, {"sql": ""}, {"sql": 5}):
        assert run_sql(RunContext("s"), args).is_error


def test_calculate_ok_and_id_sequence():
    ctx = RunContext("s")
    out = run_calculate(ctx, {"expression": "1200000 * 0.035", "label": "x"})
    assert out.payload == {"calc_id": "C1", "expression": "1200000 * 0.035", "result": "42000"}
    assert run_calculate(ctx, {"expression": "1+1"}).payload["calc_id"] == "C2"
    assert ctx.calcs["C1"].result == Decimal(42000)


def test_calculate_errors_do_not_consume_ids():
    ctx = RunContext("s")
    for expr in ("1/0", "__import__('os')", None):
        assert run_calculate(ctx, {"expression": expr}).is_error
    assert not ctx.calcs
