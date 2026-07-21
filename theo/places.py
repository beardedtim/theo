"""Interface for ingesting Theographic place data
(data/theographic/json/places.json) into the `places` and `verse_places`
tables.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from psycopg.rows import dict_row

from theo.bible import book_number
from theo.db import get_connection
from theo.theographic import load_source


@dataclass(frozen=True)
class Place:
    id: str
    kjv_name: str
    display_title: str
    feature_type: str | None
    feature_sub_type: str | None
    latitude: float | None
    longitude: float | None
    dictionary_text: str | None


def _to_float(value: str | None) -> float | None:
    return float(value) if value is not None else None


def ingest_file(path: Path) -> int:
    """Load places.json into the `places` table.

    Safe to rerun: a place already present with the same theographic_id is
    left alone. Returns the number of places submitted (not necessarily
    inserted, since duplicates are skipped).
    """
    places = load_source(path)
    rows = [
        (
            p["id"],
            p["fields"]["placeLookup"],
            p["fields"]["placeID"],
            p["fields"]["kjvName"],
            p["fields"]["displayTitle"],
            p["fields"].get("featureType"),
            p["fields"].get("featureSubType"),
            _to_float(p["fields"].get("latitude")),
            _to_float(p["fields"].get("longitude")),
            p["fields"].get("dictionaryText"),
        )
        for p in places
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO places (
                    theographic_id, place_lookup, place_num, kjv_name, display_title,
                    feature_type, feature_sub_type, latitude, longitude, dictionary_text
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (theographic_id) DO NOTHING
                """,
                rows,
            )
        conn.commit()

    return len(rows)


def ingest_verse_links(path: Path, verse_coordinates: dict[str, tuple[int, int, int]]) -> int:
    """Populate `verse_places` from places.json's `verses` reference arrays,
    resolved to (book, chapter, verse) coordinates via `verse_coordinates`
    (see theo.theographic.load_verse_coordinates).

    Safe to rerun: an existing (place_id, book, chapt_num, verse_num) row is
    left alone. Returns the number of links submitted.
    """
    places = load_source(path)
    rows = [
        (p["id"], *verse_coordinates[verse_ref])
        for p in places
        for verse_ref in p["fields"].get("verses", [])
        if verse_ref in verse_coordinates
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO verse_places (place_id, book, chapt_num, verse_num)
                SELECT id, %s, %s, %s FROM places WHERE theographic_id = %s
                ON CONFLICT (place_id, book, chapt_num, verse_num) DO NOTHING
                """,
                [(book, chapter, verse, theographic_id) for theographic_id, book, chapter, verse in rows],
            )
        conn.commit()

    return len(rows)


# --- Reading places back out of the table ------------------------------------

def _row_to_place(row: dict) -> Place:
    return Place(
        id=str(row["id"]),
        kjv_name=row["kjv_name"],
        display_title=row["display_title"],
        feature_type=row["feature_type"],
        feature_sub_type=row["feature_sub_type"],
        latitude=row["latitude"],
        longitude=row["longitude"],
        dictionary_text=row["dictionary_text"],
    )


def get_places_in_range(
    book: int | str,
    chapter_start: int,
    verse_start: int,
    chapter_end: int,
    verse_end: int,
) -> list[Place]:
    """Fetch every place mentioned anywhere in [(chapter_start, verse_start),
    (chapter_end, verse_end)] of `book`, deduplicated -- a place mentioned in
    multiple verses of the range appears once. Used to answer "where's this
    passage set" for a pericope/search result. `book` may be either its
    number (1-66) or its name (e.g. "Genesis")."""
    book_num = book if isinstance(book, int) else book_number(book)
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT DISTINCT
                    pl.id, pl.kjv_name, pl.display_title, pl.feature_type,
                    pl.feature_sub_type, pl.latitude, pl.longitude, pl.dictionary_text
                FROM places pl
                JOIN verse_places vp ON vp.place_id = pl.id
                WHERE vp.book = %s
                    AND (vp.chapt_num, vp.verse_num) >= (%s, %s)
                    AND (vp.chapt_num, vp.verse_num) <= (%s, %s)
                ORDER BY pl.kjv_name
                """,
                (book_num, chapter_start, verse_start, chapter_end, verse_end),
            )
            rows = cur.fetchall()
    return [_row_to_place(row) for row in rows]
