"""Semantic search over document chunks (pgvector cosine distance).

Runs one fixed, parameterised query on the READ-ONLY role; the model never writes this SQL, it only
supplies the search text and optional filters. The best-matching document is expanded to all of its
chunks, because a short lease abstract is the unit a reader needs and the best chunk is sometimes
the neighbouring page (measured in M2 part A: right document, wrong page in 2 of 13 queries).
"""

from functools import lru_cache

from sqlalchemy import text

from .config import settings
from .db import readonly_engine
from .embeddings import Embedder, get_embedder, vector_literal

_SELECT = (
    "SELECT ch.chunk_id, ch.document_id, d.title, d.doc_type, d.property_id, ch.page, "
    "ch.content, 1 - (ch.embedding <=> CAST(:v AS vector)) AS similarity "
    "FROM document_chunks ch JOIN documents d USING (document_id) "
)


@lru_cache
def _embedder() -> Embedder:
    return get_embedder()


def search(
    query: str, *, property_id: int | None = None, document_id: int | None = None,
    doc_type: str | None = None, top_k: int = 4,
) -> list[dict]:
    """Top-k chunks by similarity, then the rest of the best document. Hits come first."""
    vec = vector_literal(_embedder().embed([settings.embedding_query_prefix + query])[0])
    conds, params = [], {"v": vec, "k": top_k}
    for col, val in (("d.property_id", property_id), ("ch.document_id", document_id),
                     ("d.doc_type", doc_type)):
        if val is not None:
            key = col.split(".")[1]
            conds.append(f"{col} = :{key}")
            params[key] = val
    where = ("WHERE " + " AND ".join(conds) + " ") if conds else ""

    with readonly_engine().connect() as conn:
        hits = [dict(r._mapping) for r in conn.execute(
            text(_SELECT + where + "ORDER BY ch.embedding <=> CAST(:v AS vector) LIMIT :k"),
            params)]
        if not hits:
            return []
        seen = [h["chunk_id"] for h in hits]
        rest = conn.execute(
            text(_SELECT + "WHERE ch.document_id = :doc AND ch.chunk_id <> ALL(:seen) "
                 "ORDER BY ch.page, ch.chunk_id"),
            {"v": vec, "doc": hits[0]["document_id"], "seen": seen})
        extras = [dict(r._mapping) for r in rest]
    for h in hits:
        h["expanded"] = False
    for e in extras:
        e["expanded"] = True
    return hits + extras
