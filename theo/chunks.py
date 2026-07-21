"""Turn pericopes into embedded chunks in the chunks_<dimensions> table
matching whatever model theo.embeddings currently wraps.

A pericope becomes one chunk when its full verse text fits the embedding
model's context; longer pericopes are split on verse boundaries into
consecutive chunk_seq segments packed under TOKEN_BUDGET. Without the
split, everything past the model's limit is silently truncated at embed
time and invisible to semantic search (604 of the 2,227 NIV pericopes
exceed BGE's 512 tokens; Psalm 119 is 2,865). theo.search already ranks a
pericope by its best-matching chunk, so nothing downstream changes.
"""

from __future__ import annotations

import uuid

from pgvector import Vector
from psycopg import sql

from theo.bible import get_verses_in_range
from theo.db import get_connection
from theo.embeddings import DIMENSIONS, MODEL_NAME, count_tokens, embed_texts
from theo.pericopes import Pericope, list_pericopes

# Headroom under theo.embeddings.MAX_TOKENS: per-verse token counts each
# include the tokenizer's special tokens, so a packed segment's true joined
# count is slightly below the packed sum.
TOKEN_BUDGET = 480


def pack_segments(texts: list[str], token_counts: list[int], budget: int = TOKEN_BUDGET) -> list[str]:
    """Greedily pack consecutive verse texts into segments whose summed
    token counts stay within `budget`. A single verse longer than the budget
    still becomes its own segment -- no verse is ever dropped."""
    segments: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for text, tokens in zip(texts, token_counts):
        if current and current_tokens + tokens > budget:
            segments.append(" ".join(current))
            current, current_tokens = [], 0
        current.append(text)
        current_tokens += tokens
    if current:
        segments.append(" ".join(current))
    return segments


def _chunk_texts(pericope: Pericope, translation: str) -> list[str]:
    verses = get_verses_in_range(
        translation,
        pericope.book,
        pericope.chapter_start,
        pericope.verse_start,
        pericope.chapter_end,
        pericope.verse_end,
    )
    # Skip empty rows (NIV omits e.g. Matthew 17:21 to a footnote, stored as
    # an empty string) so joining can't produce doubled spaces.
    texts = [v.text for v in verses if v.text]
    if not texts:
        return []
    return pack_segments(texts, count_tokens(texts))


def embed_pericopes(translation: str = "NIV", model: str = MODEL_NAME) -> int:
    """Embed every pericope into chunks_<DIMENSIONS>, splitting pericopes
    that exceed the embedding model's token limit across several chunks.

    Diff-aware and safe to rerun: a pericope whose stored chunk texts for
    `model` already equal the planned chunking is skipped without
    re-embedding; anything else has its chunks replaced (delete + insert in
    one transaction). Returns the number of chunks written.
    """
    pericopes = list_pericopes()
    planned = {p.id: _chunk_texts(p, translation) for p in pericopes}

    table = sql.Identifier(f"chunks_{DIMENSIONS}")
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    """
                    SELECT pericope_id, raw_text FROM {table}
                    WHERE embedding_model = %s
                    ORDER BY pericope_id, chunk_seq
                    """
                ).format(table=table),
                (model,),
            )
            existing: dict[str, list[str]] = {}
            for pericope_id, raw_text in cur.fetchall():
                existing.setdefault(str(pericope_id), []).append(raw_text)

    changed = [p for p in pericopes if planned[p.id] and planned[p.id] != existing.get(p.id, [])]
    if not changed:
        return 0

    embeddings = embed_texts([text for p in changed for text in planned[p.id]])

    rows = []
    for p in changed:
        for seq, text in enumerate(planned[p.id]):
            rows.append((p.id, model, seq, text, Vector(embeddings[len(rows)])))

    delete = sql.SQL("DELETE FROM {table} WHERE embedding_model = %s AND pericope_id = ANY(%s)").format(table=table)
    insert = sql.SQL(
        """
        INSERT INTO {table} (pericope_id, embedding_model, chunk_seq, raw_text, embedding)
        VALUES (%s, %s, %s, %s, %s)
        """
    ).format(table=table)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(delete, (model, [uuid.UUID(p.id) for p in changed]))
            cur.executemany(insert, rows)
        conn.commit()

    return len(rows)
