"""CLI: ingest theographic person data into the `people`,
`person_relationships`, and `verse_people` tables.

Requires `places` to already be ingested (run ingest_places.py first) so
birth/death place references can resolve.

Usage:
    uv run ingest_people.py
"""

import sys
from pathlib import Path

import tyro

from theo.people import ingest_file, ingest_relationships, ingest_verse_links, resolve_relationships
from theo.theographic import load_verse_coordinates


def main(
    file: tyro.conf.Positional[Path] = Path("data/theographic/json/people.json"),
    verses_file: Path = Path("data/theographic/json/verses.json"),
) -> None:
    """CLI: ingest theographic person data into the `people`,
    `person_relationships`, and `verse_people` tables.

    Args:
        file: Path to theographic's people.json
        verses_file: Path to theographic's verses.json, used to resolve verse references to (book, chapter, verse)
    """
    if not file.exists():
        sys.exit(f"File not found: {file}")
    if not verses_file.exists():
        sys.exit(f"File not found: {verses_file}")

    submitted = ingest_file(file)
    print(f"Submitted {submitted} people (duplicates skipped).")

    resolved = resolve_relationships(file)
    print(f"Resolved mother/father/birth/death place for {resolved} people.")

    relationships = ingest_relationships(file)
    print(f"Submitted {relationships} sibling/partner relationships (duplicates skipped).")

    verse_coordinates = load_verse_coordinates(verses_file)
    links = ingest_verse_links(file, verse_coordinates)
    print(f"Submitted {links} person-verse links (duplicates skipped).")


if __name__ == "__main__":
    tyro.cli(main)
