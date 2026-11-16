"""Agent loop (Claude tool use). Implemented in week 2.

Planned tools:
  - run_sql(sql)            -> guarded read-only query (db.run_readonly_query)
  - search_documents(query) -> retrieval over document_chunks, returns passages + citations
  - calculate(expression)   -> deterministic math so the LLM never does arithmetic
"""
