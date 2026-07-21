"""Shared plumbing for ingesting Theographic Bible Metadata
(data/theographic/json/*.json) into Theo's schema.

Every theographic JSON file is a list of Airtable-exported records shaped
like `{"id": ..., "createdTime": ..., "fields": {...}}`. Entities
cross-reference each other via arrays of these opaque `id` strings, which
this module's `load_verse_coordinates` resolves down to Theo's own
(book, chapter, verse) coordinates.
"""

from __future__ import annotations

import json
from pathlib import Path


def load_source(path: Path) -> list[dict]:
    """Parse a theographic JSON export into its list of {id, createdTime,
    fields} records."""
    return json.loads(Path(path).read_text())


def load_verse_coordinates(path: Path) -> dict[str, tuple[int, int, int]]:
    """Build {theographic verse record id: (book, chapter, verse)} from
    data/theographic/json/verses.json.

    Every record's `fields.verseID` is an 8-digit zero-padded "BBCCCVVV"
    string (2-digit book, 3-digit chapter, 3-digit verse) -- decoding it
    directly is sufficient to resolve any other table's `verses` reference
    array without needing theographic's own books/chapters tables.
    """
    verses = load_source(path)
    coordinates = {}
    for record in verses:
        verse_id = record["fields"]["verseID"]
        book = int(verse_id[0:2])
        chapter = int(verse_id[2:5])
        verse = int(verse_id[5:8])
        coordinates[record["id"]] = (book, chapter, verse)
    return coordinates
