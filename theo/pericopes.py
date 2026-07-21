"""Interface for reading and writing pericope data (see data/pericopes.json
and build_pericopes.py for how that source file is generated).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from psycopg.rows import dict_row

from theo.bible import Verse, _row_to_verse, book_number, get_verses_in_range
from theo.bm25 import sanitize_query
from theo.db import get_connection


@dataclass(frozen=True)
class Pericope:
    id: str
    title: str
    book: int
    chapter_start: int
    verse_start: int
    chapter_end: int
    verse_end: int


@dataclass(frozen=True)
class PericopeDetail:
    pericope: Pericope
    verses: list[Verse]


def load_source(path: Path) -> list[dict]:
    """Parse a pericopes JSON file, e.g. data/pericopes.json."""
    return json.loads(Path(path).read_text())


def ingest_file(path: Path) -> int:
    """Load a pericopes JSON file into the `pericopes` table.

    Safe to rerun: a pericope already present with the same (book,
    chapter_start, verse_start, chapter_end, verse_end) is left alone.
    Returns the number of pericopes submitted (not necessarily inserted,
    since duplicates are skipped).
    """
    pericopes = load_source(path)
    rows = [
        (p["title"], p["book"], p["chapter_start"], p["verse_start"], p["chapter_end"], p["verse_end"])
        for p in pericopes
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO pericopes (raw_text, book, chapter_start, verse_start, chapter_end, verse_end)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (book, chapter_start, verse_start, chapter_end, verse_end) DO NOTHING
                """,
                rows,
            )
        conn.commit()

    return len(rows)


# --- Reading pericopes back out of the table ---------------------------------

def _row_to_pericope(row: dict) -> Pericope:
    return Pericope(
        id=str(row["id"]),
        title=row["raw_text"],
        book=row["book"],
        chapter_start=row["chapter_start"],
        verse_start=row["verse_start"],
        chapter_end=row["chapter_end"],
        verse_end=row["verse_end"],
    )


def list_pericopes(book: int | str | None = None) -> list[Pericope]:
    """List pericopes in canonical order, optionally restricted to one book.
    `book` may be either its number (1-66) or its name (e.g. "Genesis")."""
    book_num = None if book is None else (book if isinstance(book, int) else book_number(book))
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            if book_num is None:
                cur.execute(
                    """
                    SELECT id, raw_text, book, chapter_start, verse_start, chapter_end, verse_end
                    FROM pericopes
                    ORDER BY book, chapter_start, verse_start
                    """
                )
            else:
                cur.execute(
                    """
                    SELECT id, raw_text, book, chapter_start, verse_start, chapter_end, verse_end
                    FROM pericopes
                    WHERE book = %s
                    ORDER BY chapter_start, verse_start
                    """,
                    (book_num,),
                )
            rows = cur.fetchall()
    return [_row_to_pericope(row) for row in rows]


def get_pericopes_in_range(
    book: int | str,
    chapter_start: int,
    verse_start: int,
    chapter_end: int,
    verse_end: int,
) -> list[Pericope]:
    """Every pericope overlapping the range (its span intersects the query
    span), in canonical order. A manual verse range may cut across pericope
    boundaries, so this can return several. `book` may be either its number
    (1-66) or its name (e.g. "Genesis")."""
    book_num = book if isinstance(book, int) else book_number(book)
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, raw_text, book, chapter_start, verse_start, chapter_end, verse_end
                FROM pericopes
                WHERE book = %s
                    AND (chapter_start, verse_start) <= (%s, %s)
                    AND (chapter_end, verse_end) >= (%s, %s)
                ORDER BY chapter_start, verse_start
                """,
                (book_num, chapter_end, verse_end, chapter_start, verse_start),
            )
            rows = cur.fetchall()
    return [_row_to_pericope(row) for row in rows]


def get_pericope(pericope_id: str) -> Pericope | None:
    """Fetch a single pericope by id, or None if it doesn't exist."""
    try:
        uuid.UUID(pericope_id)
    except ValueError:
        return None
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, raw_text, book, chapter_start, verse_start, chapter_end, verse_end
                FROM pericopes
                WHERE id = %s
                """,
                (pericope_id,),
            )
            row = cur.fetchone()
    return _row_to_pericope(row) if row else None


def get_pericopes_by_ids(pericope_ids: list[str]) -> dict[str, Pericope]:
    """Fetch several pericopes in one query, keyed by id. Ids that don't
    exist (or aren't valid UUIDs) are simply absent from the result."""
    ids = []
    for pericope_id in pericope_ids:
        try:
            ids.append(uuid.UUID(pericope_id))
        except ValueError:
            continue
    if not ids:
        return {}
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, raw_text, book, chapter_start, verse_start, chapter_end, verse_end
                FROM pericopes
                WHERE id = ANY(%s)
                """,
                (ids,),
            )
            rows = cur.fetchall()
    return {str(row["id"]): _row_to_pericope(row) for row in rows}


def get_verses_for_pericopes(pericope_ids: list[str], translation: str = "NIV") -> dict[str, list[Verse]]:
    """Full verse text for several pericopes in one query, keyed by pericope
    id, each list in canonical order. One round trip instead of one per
    pericope -- this is how /search hydrates a whole result list."""
    ids = [uuid.UUID(pericope_id) for pericope_id in pericope_ids]
    if not ids:
        return {}
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT p.id AS pericope_id,
                       v.raw_text, v.verse_num, v.chapt_num, v.book, v.translation
                FROM pericopes p
                JOIN verses v ON v.translation = %s AND v.book = p.book
                    AND (v.chapt_num, v.verse_num) >= (p.chapter_start, p.verse_start)
                    AND (v.chapt_num, v.verse_num) <= (p.chapter_end, p.verse_end)
                WHERE p.id = ANY(%s)
                ORDER BY v.chapt_num, v.verse_num
                """,
                (translation, ids),
            )
            rows = cur.fetchall()
    verses: dict[str, list[Verse]] = {}
    for row in rows:
        verses.setdefault(str(row["pericope_id"]), []).append(_row_to_verse(row))
    return verses


def get_pericope_detail(pericope_id: str, translation: str = "NIV") -> PericopeDetail | None:
    """Fetch a pericope together with its full verse text, for reading/studying it."""
    pericope = get_pericope(pericope_id)
    if pericope is None:
        return None
    verses = get_verses_in_range(
        translation, pericope.book, pericope.chapter_start, pericope.verse_start, pericope.chapter_end, pericope.verse_end
    )
    return PericopeDetail(pericope=pericope, verses=verses)


def pericope_text(pericope: Pericope, translation: str = "NIV") -> str:
    """The pericope's full verse text joined into one string. Empty verse
    rows (NIV omits e.g. Matthew 17:21 to a footnote, stored as an empty
    string) are skipped so the join can't produce doubled spaces."""
    verses = get_verses_in_range(
        translation,
        pericope.book,
        pericope.chapter_start,
        pericope.verse_start,
        pericope.chapter_end,
        pericope.verse_end,
    )
    return " ".join(v.text for v in verses if v.text)


def search_pericopes(query: str, book: int | str | None = None, limit: int = 50) -> list[Pericope]:
    """Full-text search over pericope titles (BM25), best match first.
    `book` may optionally restrict results to one book (number or name)."""
    query = sanitize_query(query)
    if not query:
        return []

    book_num = None if book is None else (book if isinstance(book, int) else book_number(book))
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            if book_num is None:
                cur.execute(
                    """
                    SELECT id, raw_text, book, chapter_start, verse_start, chapter_end, verse_end
                    FROM pericopes
                    WHERE raw_text @@@ %s
                    ORDER BY paradedb.score(id) DESC
                    LIMIT %s
                    """,
                    (query, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT id, raw_text, book, chapter_start, verse_start, chapter_end, verse_end
                    FROM pericopes
                    WHERE raw_text @@@ %s AND book = %s
                    ORDER BY paradedb.score(id) DESC
                    LIMIT %s
                    """,
                    (query, book_num, limit),
                )
            rows = cur.fetchall()
    return [_row_to_pericope(row) for row in rows]
