"""Embedding generation via a local BAAI/bge-large-en-v1.5 model.

BGE is an asymmetric retrieval model: passages (what gets indexed) are
embedded as-is, but queries (what a user searches with) need an instruction
prefix prepended or retrieval quality silently degrades. Use `embed_texts`/
`embed_text` for passages and `embed_query` for queries.
"""

from __future__ import annotations

from functools import lru_cache

MODEL_NAME = "BAAI/bge-large-en-v1.5"
DIMENSIONS = 1024

QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Batch-embed passage/document text (no instruction prefix)."""
    embeddings = _model().encode(texts, normalize_embeddings=True, show_progress_bar=len(texts) > 1)
    return embeddings.tolist()


def embed_text(text: str) -> list[float]:
    """Embed a single passage/document."""
    return embed_texts([text])[0]


def embed_query(text: str) -> list[float]:
    """Embed a search query, with BGE's retrieval instruction prefix applied."""
    embedding = _model().encode(QUERY_INSTRUCTION + text, normalize_embeddings=True)
    return embedding.tolist()
