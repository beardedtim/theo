"""CLI: ingest theographic people-group data into the `people_groups`,
`people_group_members`, and `people_group_verses` tables.

Requires `people` to already be ingested (run ingest_people.py first) so
member references can resolve.

Usage:
    uv run ingest_people_groups.py
"""

import sys
from pathlib import Path

import tyro

from theo.people_groups import ingest_file, ingest_members, ingest_verse_links, resolve_relationships
from theo.theographic import load_verse_coordinates


def main(
    file: tyro.conf.Positional[Path] = Path("data/theographic/json/peopleGroups.json"),
    verses_file: Path = Path("data/theographic/json/verses.json"),
) -> None:
    """CLI: ingest theographic people-group data into the `people_groups`,
    `people_group_members`, and `people_group_verses` tables.

    Args:
        file: Path to theographic's peopleGroups.json
        verses_file: Path to theographic's verses.json, used to resolve verse references to (book, chapter, verse)
    """
    if not file.exists():
        sys.exit(f"File not found: {file}")
    if not verses_file.exists():
        sys.exit(f"File not found: {verses_file}")

    submitted = ingest_file(file)
    print(f"Submitted {submitted} people groups (duplicates skipped).")

    resolved = resolve_relationships(file)
    print(f"Resolved parent group for {resolved} people groups.")

    members = ingest_members(file)
    print(f"Submitted {members} group memberships (duplicates skipped).")

    verse_coordinates = load_verse_coordinates(verses_file)
    links = ingest_verse_links(file, verse_coordinates)
    print(f"Submitted {links} group-verse links (duplicates skipped).")


if __name__ == "__main__":
    tyro.cli(main)
