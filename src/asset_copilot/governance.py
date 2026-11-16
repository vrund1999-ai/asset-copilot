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

    # Embeddings are 1024 floats per row: useless to the model and they flood the context.
    if any(c.name.lower() == "embedding" for c in tree.find_all(exp.Column)):
        raise UnsafeQueryError("The 'embedding' column is not queryable.")
    touches_chunks = any(t.name.lower() == "document_chunks" for t in tree.find_all(exp.Table))
    if touches_chunks:
        for select in tree.find_all(exp.Select):
            if any(
                isinstance(e, exp.Star) or (isinstance(e, exp.Column) and isinstance(e.this, exp.Star))
                for e in select.expressions
            ):
                raise UnsafeQueryError(
                    "SELECT * on document_chunks is not allowed; list the columns you need."
                )

    if tree.args.get("limit") is None and isinstance(tree, exp.Select):
        tree = tree.limit(MAX_ROWS)
    return tree.sql(dialect="postgres")
