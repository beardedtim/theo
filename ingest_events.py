"""CLI: ingest theographic event data into the `events`, `event_parts`,
`event_people`, `event_places`, `event_groups`, and `event_verses` tables.

Requires `people`, `places`, and `people_groups` to already be ingested
(run ingest_places.py, ingest_people.py, and ingest_people_groups.py first)
so participant/location/group references can resolve.

Usage:
    uv run ingest_events.py
"""

import sys
from pathlib import Path

import tyro

from theo.events import (
    ingest_file,
    ingest_group_links,
    ingest_parts,
    ingest_people_links,
    ingest_place_links,
    ingest_verse_links,
    resolve_relationships,
)
from theo.theographic import load_verse_coordinates


def main(
    file: tyro.conf.Positional[Path] = Path("data/theographic/json/events.json"),
    verses_file: Path = Path("data/theographic/json/verses.json"),
) -> None:
    """CLI: ingest theographic event data into the `events`, `event_parts`,
    `event_people`, `event_places`, `event_groups`, and `event_verses` tables.

    Args:
        file: Path to theographic's events.json
        verses_file: Path to theographic's verses.json, used to resolve verse references to (book, chapter, verse)
    """
    if not file.exists():
        sys.exit(f"File not found: {file}")
    if not verses_file.exists():
        sys.exit(f"File not found: {verses_file}")

    submitted = ingest_file(file)
    print(f"Submitted {submitted} events (duplicates skipped).")

    resolved = resolve_relationships(file)
    print(f"Resolved predecessor for {resolved} events.")

    parts = ingest_parts(file)
    print(f"Submitted {parts} event-part edges (duplicates skipped).")

    people_links = ingest_people_links(file)
    print(f"Submitted {people_links} event-participant links (duplicates skipped).")

    place_links = ingest_place_links(file)
    print(f"Submitted {place_links} event-location links (duplicates skipped).")

    group_links = ingest_group_links(file)
    print(f"Submitted {group_links} event-group links (duplicates skipped).")

    verse_coordinates = load_verse_coordinates(verses_file)
    verse_links = ingest_verse_links(file, verse_coordinates)
    print(f"Submitted {verse_links} event-verse links (duplicates skipped).")


if __name__ == "__main__":
    tyro.cli(main)
