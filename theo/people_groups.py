"""Interface for ingesting Theographic people-group data
(data/theographic/json/peopleGroups.json) into the `people_groups`,
`people_group_members`, and `people_group_verses` tables.

Ingestion is two-pass like `theo.people`: `ingest_file` inserts every
group's scalar columns first, then `resolve_relationships` fills in
parent_group_id now that every group row exists -- that field can
reference a group appearing later in the source file.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from psycopg.rows import dict_row

from theo.db import get_connection
from theo.people import Person
from theo.theographic import load_source


@dataclass(frozen=True)
class PeopleGroup:
    id: str
    group_name: str


@dataclass(frozen=True)
class GroupDetail:
    group: PeopleGroup
    members: list[Person]


def _first_or_none(refs: list[str]) -> str | None:
    return refs[0] if refs else None


def ingest_file(path: Path) -> int:
    """Pass 1: load peopleGroups.json's scalar columns into the
    `people_groups` table.

    Safe to rerun: a group already present with the same theographic_id is
    left alone. Returns the number of groups submitted (not necessarily
    inserted, since duplicates are skipped).
    """
    groups = load_source(path)
    rows = [(g["id"], g["fields"]["groupName"]) for g in groups]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO people_groups (theographic_id, group_name)
                VALUES (%s, %s)
                ON CONFLICT (theographic_id) DO NOTHING
                """,
                rows,
            )
        conn.commit()

    return len(rows)


def resolve_relationships(path: Path) -> int:
    """Pass 2: set parent_group_id now that every group row exists.

    Safe to rerun: this is a deterministic UPDATE, not an INSERT, so its
    idempotency comes from always resolving to the same value given the
    same source data, rather than from ON CONFLICT DO NOTHING.
    """
    groups = load_source(path)
    rows = [
        (_first_or_none(g["fields"].get("partOf", [])), g["id"])
        for g in groups
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                UPDATE people_groups
                SET parent_group_id = (SELECT id FROM people_groups WHERE theographic_id = %s)
                WHERE theographic_id = %s
                """,
                rows,
            )
        conn.commit()

    return len(rows)


def ingest_members(path: Path) -> int:
    """Populate `people_group_members` from peopleGroups.json's `members`
    reference arrays.

    Safe to rerun: an existing (group_id, person_id) row is left alone.
    Returns the number of memberships submitted.
    """
    groups = load_source(path)
    rows = [
        (g["id"], member_id)
        for g in groups
        for member_id in g["fields"].get("members", [])
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO people_group_members (group_id, person_id)
                SELECT g.id, p.id
                FROM people_groups g, people p
                WHERE g.theographic_id = %s AND p.theographic_id = %s
                ON CONFLICT (group_id, person_id) DO NOTHING
                """,
                rows,
            )
        conn.commit()

    return len(rows)


def ingest_verse_links(path: Path, verse_coordinates: dict[str, tuple[int, int, int]]) -> int:
    """Populate `people_group_verses` from peopleGroups.json's `verses`
    reference arrays, resolved to (book, chapter, verse) coordinates via
    `verse_coordinates` (see theo.theographic.load_verse_coordinates).

    Safe to rerun: an existing (group_id, book, chapt_num, verse_num) row
    is left alone. Returns the number of links submitted.
    """
    groups = load_source(path)
    rows = [
        (g["id"], *verse_coordinates[verse_ref])
        for g in groups
        for verse_ref in g["fields"].get("verses", [])
        if verse_ref in verse_coordinates
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO people_group_verses (group_id, book, chapt_num, verse_num)
                SELECT id, %s, %s, %s FROM people_groups WHERE theographic_id = %s
                ON CONFLICT (group_id, book, chapt_num, verse_num) DO NOTHING
                """,
                [(book, chapter, verse, theographic_id) for theographic_id, book, chapter, verse in rows],
            )
        conn.commit()

    return len(rows)


# --- Reading groups back out of the tables -----------------------------------

def _row_to_group(row: dict) -> PeopleGroup:
    return PeopleGroup(id=str(row["id"]), group_name=row["group_name"])


def list_groups() -> list[PeopleGroup]:
    """List every people group, alphabetically."""
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT id, group_name FROM people_groups ORDER BY group_name")
            rows = cur.fetchall()
    return [_row_to_group(row) for row in rows]


def get_groups_in_range(
    book: int | str,
    chapter_start: int,
    verse_start: int,
    chapter_end: int,
    verse_end: int,
) -> list[PeopleGroup]:
    """Fetch every people group mentioned anywhere in the range,
    deduplicated. Same range shape as theo.people.get_people_in_range.
    `book` may be either its number (1-66) or its name (e.g. "Genesis")."""
    from theo.bible import book_number

    book_num = book if isinstance(book, int) else book_number(book)
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT DISTINCT g.id, g.group_name
                FROM people_groups g
                JOIN people_group_verses gv ON gv.group_id = g.id
                WHERE gv.book = %s
                    AND (gv.chapt_num, gv.verse_num) >= (%s, %s)
                    AND (gv.chapt_num, gv.verse_num) <= (%s, %s)
                ORDER BY g.group_name
                """,
                (book_num, chapter_start, verse_start, chapter_end, verse_end),
            )
            rows = cur.fetchall()
    return [_row_to_group(row) for row in rows]


def get_group(group_id: str) -> GroupDetail | None:
    """Fetch a single people group together with its resolved members, or
    None if it doesn't exist."""
    try:
        uuid.UUID(group_id)
    except ValueError:
        return None

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT id, group_name FROM people_groups WHERE id = %s", (group_id,))
            group_row = cur.fetchone()
            if group_row is None:
                return None

            cur.execute(
                """
                SELECT p.id, p.name, p.display_title, p.gender, p.also_called,
                       p.birth_year, p.death_year, p.dictionary_text
                FROM people p
                JOIN people_group_members m ON m.person_id = p.id
                WHERE m.group_id = %s
                ORDER BY p.name
                """,
                (group_id,),
            )
            member_rows = cur.fetchall()

    members = [
        Person(
            id=str(row["id"]),
            name=row["name"],
            display_title=row["display_title"],
            gender=row["gender"],
            also_called=row["also_called"],
            birth_year=row["birth_year"],
            death_year=row["death_year"],
            dictionary_text=row["dictionary_text"],
        )
        for row in member_rows
    ]
    return GroupDetail(group=_row_to_group(group_row), members=members)
