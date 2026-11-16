import pytest

from asset_copilot.governance import MAX_ROWS, UnsafeQueryError, validate_sql


def test_simple_select_gets_limit():
    out = validate_sql("SELECT * FROM properties")
    assert f"LIMIT {MAX_ROWS}" in out


def test_existing_limit_preserved():
    assert "LIMIT 5" in validate_sql("SELECT * FROM properties LIMIT 5")


def test_cte_allowed():
    sql = "WITH x AS (SELECT * FROM leases) SELECT COUNT(*) FROM x"
    validate_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE properties",
        "DELETE FROM leases",
        "UPDATE properties SET name = 'x'",
        "SELECT * FROM audit_log",
        "SELECT * FROM feedback",
        "SELECT 1; DROP TABLE properties",
        "INSERT INTO tenants (name) VALUES ('x')",
    ],
)
def test_unsafe_queries_rejected(sql):
    with pytest.raises(UnsafeQueryError):
        validate_sql(sql)
