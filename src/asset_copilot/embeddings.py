"""Text embedders for document retrieval.

`SentenceTransformerEmbedder` is the real one (local model, no API key, offline). `HashEmbedder`
is a deterministic stand-in for tests and CI so no model is ever downloaded there. Both return
L2-normalised vectors of the same dimension, so cosine distance behaves the same way.
"""

import hashlib
import math
import re
from typing import Protocol

from .config import settings


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    """Bag-of-words hashing embedder. Texts sharing words get a higher cosine similarity."""

    def __init__(self, dim: int | None = None):
        self.dim = dim or settings.embedding_dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in re.findall(r"[a-z0-9$%.,-]+", text.lower()):
            h = int.from_bytes(hashlib.md5(tok.encode()).digest()[:8], "big")
            vec[h % self.dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class SentenceTransformerEmbedder:
    """Local sentence-transformers model. Install with `pip install -e ".[embeddings]"`."""

    def __init__(self, model_name: str | None = None):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:  # pragma: no cover - depends on the optional extra
            raise RuntimeError(
                'sentence-transformers is not installed. Run: pip install -e ".[embeddings]"'
            ) from e
        self._model = SentenceTransformer(model_name or settings.embedding_model)
        self.dim = self._model.get_sentence_embedding_dimension()
        if self.dim != settings.embedding_dim:
            raise RuntimeError(
                f"Model dimension {self.dim} != schema vector({settings.embedding_dim}). "
                "Change db/schema.sql and EMBEDDING_DIM together."
            )

    def embed(self, texts: list[str]) -> list[list[float]]:
        vecs = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [v.tolist() for v in vecs]


def get_embedder() -> Embedder:
    return SentenceTransformerEmbedder()
