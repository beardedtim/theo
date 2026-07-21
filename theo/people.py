"""Interface for ingesting Theographic person data
(data/theographic/json/people.json) into the `people`, `person_relationships`,
and `verse_people` tables.

Ingestion is two-pass: `ingest_file` inserts every person's scalar columns
first, then `resolve_relationships` fills in mother_id/father_id/
birth_place_id/death_place_id now that every person and place row exists --
those fields can reference records that appear later in the source file (or,
for places, in a different file entirely).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from psycopg.rows import dict_row

from theo.bible import book_number
from theo.db import get_connection
from theo.theographic import load_source


@dataclass(frozen=True)
class Person:
    id: str
    name: str
    display_title: str
    gender: str | None
    also_called: str | None
    birth_year: int | None
    death_year: int | None
    dictionary_text: str | None

# Maps a theographic relationship field to the relation_type stored in
# person_relationships. All four are genuinely multi-valued and symmetric
# in the source (verified: siblings/half-siblings/partners are always
# listed on both sides of the pair).
_RELATIONSHIP_FIELDS = {
    "siblings": "sibling",
    "halfSiblingsSameMother": "half_sibling_maternal",
    "halfSiblingsSameFather": "half_sibling_paternal",
    "partners": "partner",
}


def _to_int(value: str | None) -> int | None:
    return int(value) if value is not None else None


def _first_or_none(refs: list[str]) -> str | None:
    return refs[0] if refs else None


def ingest_file(path: Path) -> int:
    """Pass 1: load people.json's scalar columns into the `people` table.

    Safe to rerun: a person already present with the same theographic_id is
    left alone. Returns the number of people submitted (not necessarily
    inserted, since duplicates are skipped).
    """
    people = load_source(path)
    rows = [
        (
            p["id"],
            p["fields"]["personLookup"],
            p["fields"]["personID"],
            p["fields"]["name"],
            p["fields"]["displayTitle"],
            p["fields"].get("gender"),
            p["fields"].get("isProperName"),
            p["fields"].get("alsoCalled"),
            p["fields"].get("dictionaryText"),
            _to_int(p["fields"].get("birthYear")),
            _to_int(p["fields"].get("deathYear")),
        )
        for p in people
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO people (
                    theographic_id, person_lookup, person_num, name, display_title,
                    gender, is_proper_name, also_called, dictionary_text, birth_year, death_year
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (theographic_id) DO NOTHING
                """,
                rows,
            )
        conn.commit()

    return len(rows)


def resolve_relationships(path: Path) -> int:
    """Pass 2: set mother_id/father_id/birth_place_id/death_place_id now
    that every person and place row exists.

    Safe to rerun: this is a deterministic UPDATE, not an INSERT, so its
    idempotency comes from always resolving to the same values given the
    same source data, rather than from ON CONFLICT DO NOTHING.
    """
    people = load_source(path)
    rows = [
        (
            _first_or_none(p["fields"].get("mother", [])),
            _first_or_none(p["fields"].get("father", [])),
            _first_or_none(p["fields"].get("birthPlace", [])),
            _first_or_none(p["fields"].get("deathPlace", [])),
            p["id"],
        )
        for p in people
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                UPDATE people
                SET mother_id = (SELECT id FROM people WHERE theographic_id = %s),
                    father_id = (SELECT id FROM people WHERE theographic_id = %s),
                    birth_place_id = (SELECT id FROM places WHERE theographic_id = %s),
                    death_place_id = (SELECT id FROM places WHERE theographic_id = %s)
                WHERE theographic_id = %s
                """,
                rows,
            )
        conn.commit()

    return len(rows)


def ingest_relationships(path: Path) -> int:
    """Populate `person_relationships` from people.json's sibling/
    half-sibling/partner reference arrays.

    Safe to rerun: an existing (person_id, related_person_id, relation_type)
    row is left alone. Returns the number of relationship edges submitted.
    """
    people = load_source(path)
    rows = [
        (p["id"], related_id, relation_type)
        for p in people
        for field, relation_type in _RELATIONSHIP_FIELDS.items()
        for related_id in p["fields"].get(field, [])
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO person_relationships (person_id, related_person_id, relation_type)
                SELECT p1.id, p2.id, %s
                FROM people p1, people p2
                WHERE p1.theographic_id = %s AND p2.theographic_id = %s
                ON CONFLICT (person_id, related_person_id, relation_type) DO NOTHING
                """,
                [(relation_type, theographic_id, related_id) for theographic_id, related_id, relation_type in rows],
            )
        conn.commit()

    return len(rows)


def ingest_verse_links(path: Path, verse_coordinates: dict[str, tuple[int, int, int]]) -> int:
    """Populate `verse_people` from people.json's `verses` reference arrays,
    resolved to (book, chapter, verse) coordinates via `verse_coordinates`
    (see theo.theographic.load_verse_coordinates).

    Safe to rerun: an existing (person_id, book, chapt_num, verse_num) row
    is left alone. Returns the number of links submitted.
    """
    people = load_source(path)
    rows = [
        (p["id"], *verse_coordinates[verse_ref])
        for p in people
        for verse_ref in p["fields"].get("verses", [])
        if verse_ref in verse_coordinates
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO verse_people (person_id, book, chapt_num, verse_num)
                SELECT id, %s, %s, %s FROM people WHERE theographic_id = %s
                ON CONFLICT (person_id, book, chapt_num, verse_num) DO NOTHING
                """,
                [(book, chapter, verse, theographic_id) for theographic_id, book, chapter, verse in rows],
            )
        conn.commit()

    return len(rows)


# --- Reading people back out of the table ------------------------------------

def _row_to_person(row: dict) -> Person:
    return Person(
        id=str(row["id"]),
        name=row["name"],
        display_title=row["display_title"],
        gender=row["gender"],
        also_called=row["also_called"],
        birth_year=row["birth_year"],
        death_year=row["death_year"],
        dictionary_text=row["dictionary_text"],
    )


def get_people_in_range(
    book: int | str,
    chapter_start: int,
    verse_start: int,
    chapter_end: int,
    verse_end: int,
) -> list[Person]:
    """Fetch every person mentioned anywhere in [(chapter_start, verse_start),
    (chapter_end, verse_end)] of `book`, deduplicated -- a person mentioned in
    multiple verses of the range appears once. Used to answer "who's in this
    passage" for a pericope/search result. `book` may be either its number
    (1-66) or its name (e.g. "Genesis")."""
    book_num = book if isinstance(book, int) else book_number(book)
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT DISTINCT
                    p.id, p.name, p.display_title, p.gender, p.also_called,
                    p.birth_year, p.death_year, p.dictionary_text
                FROM people p
                JOIN verse_people vp ON vp.person_id = p.id
                WHERE vp.book = %s
                    AND (vp.chapt_num, vp.verse_num) >= (%s, %s)
                    AND (vp.chapt_num, vp.verse_num) <= (%s, %s)
                ORDER BY p.name
                """,
                (book_num, chapter_start, verse_start, chapter_end, verse_end),
            )
            rows = cur.fetchall()
    return [_row_to_person(row) for row in rows]
