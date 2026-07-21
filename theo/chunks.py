"""Turn pericopes into embedded chunks in the chunks_<dimensions> table
matching whatever model theo.embeddings currently wraps.

For now each pericope becomes exactly one chunk (chunk_seq=0) holding its
full verse text -- revisit chunk_seq splitting if a pericope turns out to be
too big for the embedding model in use (BAAI/bge-large-en-v1.5 truncates
anything past 512 tokens, e.g. Psalm 119).
"""

from __future__ import annotations

from pgvector import Vector
from psycopg import sql

from theo.bible import get_verses_in_range
from theo.db import get_connection
from theo.embeddings import DIMENSIONS, MODEL_NAME, embed_texts
from theo.pericopes import Pericope, list_pericopes


def _chunk_text(pericope: Pericope, translation: str) -> str:
    verses = get_verses_in_range(
        translation,
        pericope.book,
        pericope.chapter_start,
        pericope.verse_start,
        pericope.chapter_end,
        pericope.verse_end,
    )
    return " ".join(v.text for v in verses)


def embed_pericopes(translation: str = "NIV", model: str = MODEL_NAME) -> int:
    """Embed every pericope as a single chunk and store it in chunks_<DIMENSIONS>.

    Safe to rerun: an existing (pericope_id, embedding_model, chunk_seq) row
    is left alone. Returns the number of chunks submitted (not necessarily
    inserted, since duplicates are skipped).
    """
    pericopes = [p for p in list_pericopes()]
    texts = [_chunk_text(p, translation) for p in pericopes]
    keep = [(p, text) for p, text in zip(pericopes, texts) if text]
    if not keep:
        return 0

    embeddings = embed_texts([text for _, text in keep])
    rows = [
        (pericope.id, model, 0, text, Vector(embedding))
        for (pericope, text), embedding in zip(keep, embeddings)
    ]

    table = sql.Identifier(f"chunks_{DIMENSIONS}")
    insert = sql.SQL(
        """
        INSERT INTO {table} (pericope_id, embedding_model, chunk_seq, raw_text, embedding)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (pericope_id, embedding_model, chunk_seq) DO NOTHING
        """
    ).format(table=table)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(insert, rows)
        conn.commit()

    return len(rows)
