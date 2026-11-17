"""Load generated documents into `documents` / `document_chunks` with embeddings.

Usage:  python -m asset_copilot.ingest   (after `python -m asset_copilot.synth.documents`)

Pipeline: read manifest -> split each file into pages -> chunk each page (page number kept) ->
embed (title + chunk, so a chunk carries its document context) -> insert. Re-running replaces all
documents. `leases.document_id` is set for lease abstracts.
"""

import argparse
import json
import re
from pathlib import Path

from sqlalchemy import text

from .config import settings
from .db import admin_engine
from .embeddings import Embedder, get_embedder, vector_literal

PAGE_RE = re.compile(r"^<!-- page (\d+) -->[ \t]*$", re.MULTILINE)
MAX_CHUNK_CHARS = 900


def parse_pages(raw: str) -> list[tuple[int, str]]:
    """Split a document into (page_number, text). Text before the first marker is page 1."""
    marks = list(PAGE_RE.finditer(raw))
    if not marks:
        return [(1, raw.strip())] if raw.strip() else []
    pages = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(raw)
        body = raw[m.end():end].strip()
        if body:
            pages.append((int(m.group(1)), body))
    return pages


def chunk_page(page_text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Pack paragraphs into chunks of at most max_chars; hard-split any single oversize paragraph."""
    chunks: list[str] = []
    current = ""
    for para in (p.strip() for p in re.split(r"\n\s*\n", page_text)):
        if not para:
            continue
        while len(para) > max_chars:  # rare for these documents; keeps the bound honest
            cut = para.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            if current:
                chunks.append(current)
                current = ""
            chunks.append(para[:cut].strip())
            para = para[cut:].strip()
        if current and len(current) + 2 + len(para) > max_chars:
            chunks.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current)
    return chunks


def build_rows(manifest: dict, base: Path, embedder: Embedder, batch_size: int = 32) -> list[dict]:
    """Pure (no DB): manifest + files -> one dict per document, each with embedded chunks."""
    rows = []
    for d in manifest["documents"]:
        raw = (base / d["file"]).read_text(encoding="utf-8")
        chunks = [(page, c) for page, body in parse_pages(raw) for c in chunk_page(body)]
        inputs = [f"{d['title']}\n{c}" for _, c in chunks]
        vectors: list[list[float]] = []
        for i in range(0, len(inputs), batch_size):
            vectors.extend(embedder.embed(inputs[i:i + batch_size]))
        rows.append({**d, "chunks": [
            {"page": page, "content": c, "embedding": v}
            for (page, c), v in zip(chunks, vectors, strict=True)]})
    return rows


def load_rows(rows: list[dict]) -> tuple[int, int]:
    n_chunks = 0
    with admin_engine().begin() as conn:
        conn.execute(text("UPDATE leases SET document_id = NULL"))
        conn.execute(text("TRUNCATE document_chunks, documents RESTART IDENTITY CASCADE"))
        for r in rows:
            doc_id = conn.execute(
                text("INSERT INTO documents (property_id, doc_type, title) "
                     "VALUES (:p, :t, :ti) RETURNING document_id"),
                {"p": r["property_id"], "t": r["doc_type"], "ti": r["title"]},
            ).scalar_one()
            if r.get("lease_id"):
                conn.execute(text("UPDATE leases SET document_id = :d WHERE lease_id = :l"),
                             {"d": doc_id, "l": r["lease_id"]})
            for c in r["chunks"]:
                conn.execute(
                    text("INSERT INTO document_chunks (document_id, page, content, embedding) "
                         "VALUES (:d, :pg, :c, CAST(:e AS vector))"),
                    {"d": doc_id, "pg": c["page"], "c": c["content"], "e": vector_literal(c["embedding"])})
                n_chunks += 1
    return len(rows), n_chunks


def ingest(base: Path | None = None, embedder: Embedder | None = None) -> tuple[int, int]:
    base = base or Path(settings.generated_dir)
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    rows = build_rows(manifest, base, embedder or get_embedder())
    return load_rows(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=Path(settings.generated_dir))
    args = ap.parse_args()
    n_docs, n_chunks = ingest(args.dir)
    print(f"Ingested {n_docs} documents, {n_chunks} chunks.")


if __name__ == "__main__":
    main()
