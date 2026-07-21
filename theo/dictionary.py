"""Interface for ingesting Easton's Bible Dictionary (1897), as
cross-linked by Theographic Bible Metadata (data/theographic/json/easton.json),
into the `dictionary_entries`, `dictionary_entry_people`, and
`dictionary_entry_places` tables.

Requires `people` and `places` to already be ingested so an entry's
person/place cross-links can resolve. No self-references, so unlike
theo.people/theo.events/theo.people_groups this is single-pass.

Despite their field names, easton.json's `personLookup`/`placeLookup`
arrays hold Airtable record ids (matching people.json/places.json's own
`id`), not the `person_lookup`/`place_lookup` slug strings -- verified
directly against the source data.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from psycopg.rows import dict_row

from theo.db import get_connection
from theo.theographic import load_source


@dataclass(frozen=True)
class DictionaryEntry:
    id: str
    term: str
    entry_text: str | None


def ingest_file(path: Path) -> int:
    """Load easton.json's scalar columns into the `dictionary_entries`
    table.

    Safe to rerun: an entry already present with the same theographic_id is
    left alone. Returns the number of entries submitted (not necessarily
    inserted, since duplicates are skipped).
    """
    entries = load_source(path)
    rows = [
        (e["id"], e["fields"]["termLabel"], e["fields"].get("dictText"), e["fields"]["index"])
        for e in entries
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO dictionary_entries (theographic_id, term, entry_text, entry_order)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (theographic_id) DO NOTHING
                """,
                rows,
            )
        conn.commit()

    return len(rows)


def ingest_person_links(path: Path) -> int:
    """Populate `dictionary_entry_people` from easton.json's `personLookup`
    reference arrays.

    Safe to rerun: an existing (dictionary_entry_id, person_id) row is left
    alone. Returns the number of links submitted.
    """
    entries = load_source(path)
    rows = [
        (e["id"], person_id)
        for e in entries
        for person_id in e["fields"].get("personLookup", [])
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO dictionary_entry_people (dictionary_entry_id, person_id)
                SELECT d.id, p.id
                FROM dictionary_entries d, people p
                WHERE d.theographic_id = %s AND p.theographic_id = %s
                ON CONFLICT (dictionary_entry_id, person_id) DO NOTHING
                """,
                rows,
            )
        conn.commit()

    return len(rows)


def ingest_place_links(path: Path) -> int:
    """Populate `dictionary_entry_places` from easton.json's `placeLookup`
    reference arrays.

    Safe to rerun: an existing (dictionary_entry_id, place_id) row is left
    alone. Returns the number of links submitted.
    """
    entries = load_source(path)
    rows = [
        (e["id"], place_id)
        for e in entries
        for place_id in e["fields"].get("placeLookup", [])
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO dictionary_entry_places (dictionary_entry_id, place_id)
                SELECT d.id, pl.id
                FROM dictionary_entries d, places pl
                WHERE d.theographic_id = %s AND pl.theographic_id = %s
                ON CONFLICT (dictionary_entry_id, place_id) DO NOTHING
                """,
                rows,
            )
        conn.commit()

    return len(rows)


# --- Reading entries back out of the table ------------------------------------

def _row_to_entry(row: dict) -> DictionaryEntry:
    return DictionaryEntry(id=str(row["id"]), term=row["term"], entry_text=row["entry_text"])


def search_dictionary(query: str, limit: int = 50) -> list[DictionaryEntry]:
    """Full-text search over dictionary terms and definitions (BM25), best
    match first."""
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, term, entry_text, paradedb.score(id) AS score
                FROM dictionary_entries
                WHERE term @@@ %(query)s OR entry_text @@@ %(query)s
                ORDER BY score DESC
                LIMIT %(limit)s
                """,
                {"query": query, "limit": limit},
            )
            rows = cur.fetchall()
    return [_row_to_entry(row) for row in rows]


def get_dictionary_entry(entry_id: str) -> DictionaryEntry | None:
    """Fetch a single dictionary entry by id, or None if it doesn't exist."""
    try:
        uuid.UUID(entry_id)
    except ValueError:
        return None
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id, term, entry_text FROM dictionary_entries WHERE id = %s",
                (entry_id,),
            )
            row = cur.fetchone()
    return _row_to_entry(row) if row else None
