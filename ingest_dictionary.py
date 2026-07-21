"""CLI: ingest Easton's Bible Dictionary into the `dictionary_entries`,
`dictionary_entry_people`, and `dictionary_entry_places` tables.

Requires `people` and `places` to already be ingested (run
ingest_places.py and ingest_people.py first) so entry cross-links can
resolve.

Usage:
    uv run ingest_dictionary.py
"""

import sys
from pathlib import Path

import tyro

from theo.dictionary import ingest_file, ingest_person_links, ingest_place_links


def main(file: tyro.conf.Positional[Path] = Path("data/theographic/json/easton.json")) -> None:
    """CLI: ingest Easton's Bible Dictionary into the `dictionary_entries`,
    `dictionary_entry_people`, and `dictionary_entry_places` tables.

    Args:
        file: Path to theographic's easton.json
    """
    if not file.exists():
        sys.exit(f"File not found: {file}")

    submitted = ingest_file(file)
    print(f"Submitted {submitted} dictionary entries (duplicates skipped).")

    person_links = ingest_person_links(file)
    print(f"Submitted {person_links} entry-person links (duplicates skipped).")

    place_links = ingest_place_links(file)
    print(f"Submitted {place_links} entry-place links (duplicates skipped).")


if __name__ == "__main__":
    tyro.cli(main)
