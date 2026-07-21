"""CLI: ingest theographic place data into the `places` and `verse_places`
tables.

Usage:
    uv run ingest_places.py
"""

import sys
from pathlib import Path

import tyro

from theo.places import ingest_file, ingest_verse_links
from theo.theographic import load_verse_coordinates


def main(
    file: tyro.conf.Positional[Path] = Path("data/theographic/json/places.json"),
    verses_file: Path = Path("data/theographic/json/verses.json"),
) -> None:
    """CLI: ingest theographic place data into the `places` and `verse_places` tables.

    Args:
        file: Path to theographic's places.json
        verses_file: Path to theographic's verses.json, used to resolve verse references to (book, chapter, verse)
    """
    if not file.exists():
        sys.exit(f"File not found: {file}")
    if not verses_file.exists():
        sys.exit(f"File not found: {verses_file}")

    submitted = ingest_file(file)
    print(f"Submitted {submitted} places (duplicates skipped).")

    verse_coordinates = load_verse_coordinates(verses_file)
    links = ingest_verse_links(file, verse_coordinates)
    print(f"Submitted {links} place-verse links (duplicates skipped).")


if __name__ == "__main__":
    tyro.cli(main)
