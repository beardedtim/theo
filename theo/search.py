"""Search the Bible for verses related to a natural-language query.

Three modes, all returning the same SearchResult shape (a pericope, its full
verse text, and a relevance score, best match first):

- semantic: cosine similarity between the query's embedding and each
  pericope's chunk embedding(s) (theo.embeddings.embed_query / chunks_<DIM>).
- bm25: keyword full-text search over chunk text (chunks_<DIM>.raw_text).
- hybrid: reciprocal rank fusion of the two rankings above. Semantic
  similarity and BM25 relevance live on different, unnormalized scales, so
  rather than combine the raw scores this fuses by rank -- the standard way
  to blend heterogeneous search signals without score calibration.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from pgvector import Vector
from psycopg import sql
from psycopg.rows import dict_row

from theo.bible import Verse, get_verses_in_range
from theo.db import get_connection
from theo.embeddings import DIMENSIONS, MODEL_NAME, embed_query
from theo.pericopes import Pericope, get_pericope

SearchMode = Literal["semantic", "bm25", "hybrid"]

RRF_K = 60  # standard reciprocal-rank-fusion constant


@dataclass(frozen=True)
class SearchResult:
    pericope: Pericope
    verses: list[Verse]
    score: float


def _table():
    return sql.Identifier(f"chunks_{DIMENSIONS}")


def _results_from_pericope_scores(scores: list[tuple[str, float]], translation: str) -> list[SearchResult]:
    """scores: [(pericope_id, score), ...] already ranked best-first."""
    results = []
    for pericope_id, score in scores:
        pericope = get_pericope(pericope_id)
        if pericope is None:
            continue
        verses = get_verses_in_range(
            translation,
            pericope.book,
            pericope.chapter_start,
            pericope.verse_start,
            pericope.chapter_end,
            pericope.verse_end,
        )
        results.append(SearchResult(pericope=pericope, verses=verses, score=score))
    return results


def semantic_search(query: str, translation: str = "NIV", limit: int = 10, model: str = MODEL_NAME) -> list[SearchResult]:
    """Rank pericopes by cosine similarity between the query and each pericope's chunk embedding."""
    query_embedding = Vector(embed_query(query))

    # DISTINCT ON picks each pericope's single best-matching chunk, so a
    # pericope can't appear twice even once it has more than one chunk.
    stmt = sql.SQL(
        """
        SELECT pericope_id, distance FROM (
            SELECT DISTINCT ON (pericope_id) pericope_id, embedding <=> %(query)s AS distance
            FROM {table}
            WHERE embedding_model = %(model)s
            ORDER BY pericope_id, distance ASC
        ) best_chunk_per_pericope
        ORDER BY distance ASC
        LIMIT %(limit)s
        """
    ).format(table=_table())

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(stmt, {"query": query_embedding, "model": model, "limit": limit})
            rows = cur.fetchall()

    scores = [(str(row["pericope_id"]), 1 - row["distance"]) for row in rows]
    return _results_from_pericope_scores(scores, translation)


def bm25_search(query: str, translation: str = "NIV", limit: int = 10, model: str = MODEL_NAME) -> list[SearchResult]:
    """Rank pericopes by BM25 relevance of the query against each pericope's chunk text."""
    stmt = sql.SQL(
        """
        SELECT pericope_id, relevance FROM (
            SELECT DISTINCT ON (pericope_id) pericope_id, paradedb.score(id) AS relevance
            FROM {table}
            WHERE raw_text @@@ %(query)s AND embedding_model = %(model)s
            ORDER BY pericope_id, paradedb.score(id) DESC
        ) best_chunk_per_pericope
        ORDER BY relevance DESC
        LIMIT %(limit)s
        """
    ).format(table=_table())

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(stmt, {"query": query, "model": model, "limit": limit})
            rows = cur.fetchall()

    scores = [(str(row["pericope_id"]), float(row["relevance"])) for row in rows]
    return _results_from_pericope_scores(scores, translation)


def hybrid_search(
    query: str, translation: str = "NIV", limit: int = 10, model: str = MODEL_NAME, candidate_pool: int = 50
) -> list[SearchResult]:
    """Blend semantic and BM25 rankings via reciprocal rank fusion: each
    result's fused score is the sum of 1/(RRF_K + rank) across whichever
    ranking(s) it appears in."""
    cleaned_query = query.replace("'", "")
    semantic_results = semantic_search(cleaned_query, translation, limit=candidate_pool, model=model)
    bm25_results = bm25_search(cleaned_query, translation, limit=candidate_pool, model=model)

    fused_scores: dict[str, float] = {}
    result_by_id: dict[str, SearchResult] = {}
    for ranking in (semantic_results, bm25_results):
        for rank, result in enumerate(ranking, start=1):
            fused_scores[result.pericope.id] = fused_scores.get(result.pericope.id, 0.0) + 1 / (RRF_K + rank)
            result_by_id.setdefault(result.pericope.id, result)

    ranked_ids = sorted(fused_scores, key=lambda pid: fused_scores[pid], reverse=True)[:limit]
    return [replace(result_by_id[pid], score=fused_scores[pid]) for pid in ranked_ids]


_MODES = {
    "semantic": semantic_search,
    "bm25": bm25_search,
    "hybrid": hybrid_search,
}


def search(
    query: str, mode: SearchMode = "hybrid", translation: str = "NIV", limit: int = 10, model: str = MODEL_NAME
) -> list[SearchResult]:
    """Search for pericopes related to `query`. `mode` is "semantic" (vector
    similarity), "bm25" (keyword relevance), or "hybrid" (both, fused by rank)."""
    try:
        fn = _MODES[mode]
    except KeyError:
        raise ValueError(f"Unknown search mode {mode!r}; expected one of {sorted(_MODES)}") from None
    return fn(query, translation=translation, limit=limit, model=model)
