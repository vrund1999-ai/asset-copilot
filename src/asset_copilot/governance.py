"""SQL guardrails: the agent may only run a single read-only SELECT on allow-listed tables.

This is defense in depth. The DB role is also read-only (db/roles.sql).
"""

import sqlglot
from sqlglot import exp

ALLOWED_TABLES = {
    "properties",
    "tenants",
    "leases",
    "operating_statements",
    "budgets",
    "debt",
    "documents",
    "document_chunks",
}
MAX_ROWS = 500


class UnsafeQueryError(ValueError):
    pass


def validate_sql(sql: str) -> str:
    """Return a safe version of the query (with a LIMIT) or raise UnsafeQueryError."""
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except sqlglot.errors.ParseError as e:
        raise UnsafeQueryError(f"Could not parse SQL: {e}") from e

    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise UnsafeQueryError("Exactly one statement is allowed.")
    tree = statements[0]

    if not isinstance(tree, exp.Select | exp.Union | exp.With):
        raise UnsafeQueryError("Only SELECT queries are allowed.")

    forbidden = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter, exp.Command)
    if any(tree.find(node) for node in forbidden):
        raise UnsafeQueryError("Data-modifying statements are not allowed.")

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        if name not in ALLOWED_TABLES and name not in cte_names:
            raise UnsafeQueryError(f"Table '{table.name}' is not allowed.")

    if tree.args.get("limit") is None and isinstance(tree, exp.Select):
        tree = tree.limit(MAX_ROWS)
    return tree.sql(dialect="postgres")
