"""Interface for ingesting Theographic event data
(data/theographic/json/events.json) into the `events`, `event_parts`,
`event_people`, `event_places`, `event_groups`, and `event_verses` tables.

Requires `people`, `places`, and `people_groups` to already be ingested
(run ingest_people_groups.py first, which itself requires ingest_people.py
and ingest_places.py) so participant/location/group references can
resolve.

Ingestion is two-pass like `theo.people`: `ingest_file` inserts every
event's scalar columns first, then `resolve_relationships` fills in
predecessor_id now that every event row exists -- that field can
reference an event appearing later in the source file.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from psycopg.rows import dict_row

from theo.bible import book_number
from theo.db import get_connection
from theo.people import Person
from theo.places import Place
from theo.theographic import load_source


@dataclass(frozen=True)
class Event:
    id: str
    title: str
    start_date: str | None
    duration: str | None
    sort_key: float | None


@dataclass(frozen=True)
class EventDetail:
    event: Event
    participants: list[Person]
    locations: list[Place]


def _first_or_none(refs: list[str]) -> str | None:
    return refs[0] if refs else None


def ingest_file(path: Path) -> int:
    """Pass 1: load events.json's scalar columns into the `events` table.

    Safe to rerun: an event already present with the same theographic_id is
    left alone. Returns the number of events submitted (not necessarily
    inserted, since duplicates are skipped).
    """
    events = load_source(path)
    rows = [
        (
            e["id"],
            e["fields"]["eventID"],
            e["fields"]["title"],
            e["fields"].get("startDate"),
            e["fields"].get("duration"),
            e["fields"].get("sortKey"),
        )
        for e in events
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO events (theographic_id, event_num, title, start_date, duration, sort_key)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (theographic_id) DO NOTHING
                """,
                rows,
            )
        conn.commit()

    return len(rows)


def resolve_relationships(path: Path) -> int:
    """Pass 2: set predecessor_id now that every event row exists.

    Safe to rerun: this is a deterministic UPDATE, not an INSERT, so its
    idempotency comes from always resolving to the same value given the
    same source data, rather than from ON CONFLICT DO NOTHING.
    """
    events = load_source(path)
    rows = [
        (_first_or_none(e["fields"].get("predecessor", [])), e["id"])
        for e in events
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                UPDATE events
                SET predecessor_id = (SELECT id FROM events WHERE theographic_id = %s)
                WHERE theographic_id = %s
                """,
                rows,
            )
        conn.commit()

    return len(rows)


def ingest_parts(path: Path) -> int:
    """Populate `event_parts` from events.json's `partOf` reference arrays
    (which larger event(s) this event is part of).

    Safe to rerun: an existing (event_id, parent_event_id) row is left
    alone. Returns the number of edges submitted.
    """
    events = load_source(path)
    rows = [
        (e["id"], parent_id)
        for e in events
        for parent_id in e["fields"].get("partOf", [])
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO event_parts (event_id, parent_event_id)
                SELECT c.id, p.id
                FROM events c, events p
                WHERE c.theographic_id = %s AND p.theographic_id = %s
                ON CONFLICT (event_id, parent_event_id) DO NOTHING
                """,
                rows,
            )
        conn.commit()

    return len(rows)


def ingest_people_links(path: Path) -> int:
    """Populate `event_people` from events.json's `participants` reference
    arrays.

    Safe to rerun: an existing (event_id, person_id) row is left alone.
    Returns the number of links submitted.
    """
    events = load_source(path)
    rows = [
        (e["id"], person_id)
        for e in events
        for person_id in e["fields"].get("participants", [])
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO event_people (event_id, person_id)
                SELECT ev.id, p.id
                FROM events ev, people p
                WHERE ev.theographic_id = %s AND p.theographic_id = %s
                ON CONFLICT (event_id, person_id) DO NOTHING
                """,
                rows,
            )
        conn.commit()

    return len(rows)


def ingest_place_links(path: Path) -> int:
    """Populate `event_places` from events.json's `locations` reference
    arrays.

    Safe to rerun: an existing (event_id, place_id) row is left alone.
    Returns the number of links submitted.
    """
    events = load_source(path)
    rows = [
        (e["id"], place_id)
        for e in events
        for place_id in e["fields"].get("locations", [])
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO event_places (event_id, place_id)
                SELECT ev.id, pl.id
                FROM events ev, places pl
                WHERE ev.theographic_id = %s AND pl.theographic_id = %s
                ON CONFLICT (event_id, place_id) DO NOTHING
                """,
                rows,
            )
        conn.commit()

    return len(rows)


def ingest_group_links(path: Path) -> int:
    """Populate `event_groups` from events.json's `groups` reference
    arrays. Requires `people_groups` to already be ingested.

    Safe to rerun: an existing (event_id, group_id) row is left alone.
    Returns the number of links submitted.
    """
    events = load_source(path)
    rows = [
        (e["id"], group_id)
        for e in events
        for group_id in e["fields"].get("groups", [])
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO event_groups (event_id, group_id)
                SELECT ev.id, g.id
                FROM events ev, people_groups g
                WHERE ev.theographic_id = %s AND g.theographic_id = %s
                ON CONFLICT (event_id, group_id) DO NOTHING
                """,
                rows,
            )
        conn.commit()

    return len(rows)


def ingest_verse_links(path: Path, verse_coordinates: dict[str, tuple[int, int, int]]) -> int:
    """Populate `event_verses` from events.json's `verses` reference
    arrays, resolved to (book, chapter, verse) coordinates via
    `verse_coordinates` (see theo.theographic.load_verse_coordinates).

    Safe to rerun: an existing (event_id, book, chapt_num, verse_num) row
    is left alone. Returns the number of links submitted.
    """
    events = load_source(path)
    rows = [
        (e["id"], *verse_coordinates[verse_ref])
        for e in events
        for verse_ref in e["fields"].get("verses", [])
        if verse_ref in verse_coordinates
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO event_verses (event_id, book, chapt_num, verse_num)
                SELECT id, %s, %s, %s FROM events WHERE theographic_id = %s
                ON CONFLICT (event_id, book, chapt_num, verse_num) DO NOTHING
                """,
                [(book, chapter, verse, theographic_id) for theographic_id, book, chapter, verse in rows],
            )
        conn.commit()

    return len(rows)


# --- Reading events back out of the tables ------------------------------------

def _row_to_event(row: dict) -> Event:
    return Event(
        id=str(row["id"]),
        title=row["title"],
        start_date=row["start_date"],
        duration=row["duration"],
        sort_key=row["sort_key"],
    )


def list_events() -> list[Event]:
    """List every event in chronological order."""
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, title, start_date, duration, sort_key
                FROM events
                ORDER BY sort_key
                """
            )
            rows = cur.fetchall()
    return [_row_to_event(row) for row in rows]


def get_events_in_range(
    book: int | str,
    chapter_start: int,
    verse_start: int,
    chapter_end: int,
    verse_end: int,
) -> list[Event]:
    """Fetch every event mentioned anywhere in [(chapter_start, verse_start),
    (chapter_end, verse_end)] of `book`, deduplicated and chronologically
    ordered. Used to answer "what happened in this passage" for a
    pericope/search result. `book` may be either its number (1-66) or its
    name (e.g. "Genesis")."""
    book_num = book if isinstance(book, int) else book_number(book)
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT DISTINCT
                    ev.id, ev.title, ev.start_date, ev.duration, ev.sort_key
                FROM events ev
                JOIN event_verses vr ON vr.event_id = ev.id
                WHERE vr.book = %s
                    AND (vr.chapt_num, vr.verse_num) >= (%s, %s)
                    AND (vr.chapt_num, vr.verse_num) <= (%s, %s)
                ORDER BY ev.sort_key
                """,
                (book_num, chapter_start, verse_start, chapter_end, verse_end),
            )
            rows = cur.fetchall()
    return [_row_to_event(row) for row in rows]


def get_event(event_id: str) -> EventDetail | None:
    """Fetch a single event together with its resolved participants and
    locations, or None if it doesn't exist."""
    try:
        uuid.UUID(event_id)
    except ValueError:
        return None

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id, title, start_date, duration, sort_key FROM events WHERE id = %s",
                (event_id,),
            )
            event_row = cur.fetchone()
            if event_row is None:
                return None

            cur.execute(
                """
                SELECT p.id, p.name, p.display_title, p.gender, p.also_called,
                       p.birth_year, p.death_year, p.dictionary_text
                FROM people p
                JOIN event_people ep ON ep.person_id = p.id
                WHERE ep.event_id = %s
                ORDER BY p.name
                """,
                (event_id,),
            )
            participant_rows = cur.fetchall()

            cur.execute(
                """
                SELECT pl.id, pl.kjv_name, pl.display_title, pl.feature_type,
                       pl.feature_sub_type, pl.latitude, pl.longitude, pl.dictionary_text
                FROM places pl
                JOIN event_places epl ON epl.place_id = pl.id
                WHERE epl.event_id = %s
                ORDER BY pl.kjv_name
                """,
                (event_id,),
            )
            location_rows = cur.fetchall()

    participants = [
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
        for row in participant_rows
    ]
    locations = [
        Place(
            id=str(row["id"]),
            kjv_name=row["kjv_name"],
            display_title=row["display_title"],
            feature_type=row["feature_type"],
            feature_sub_type=row["feature_sub_type"],
            latitude=row["latitude"],
            longitude=row["longitude"],
            dictionary_text=row["dictionary_text"],
        )
        for row in location_rows
    ]
    return EventDetail(event=_row_to_event(event_row), participants=participants, locations=locations)
