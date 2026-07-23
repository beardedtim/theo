"""CLI: ingest jburson/bible-data's word-formatted NIV text into the
`reading_verses` and `reading_headings` tables (paragraph/poetry layout +
inline styling for the reading view). NIV only for now.

Usage:
    uv run -m scripts.ingest_reading
"""

import sys
from pathlib import Path

import tyro

from theo.reading import ingest_file


def main(
    file: tyro.conf.Positional[Path] = Path("data/info/data/niv/niv.json"),
    # Hardcoded, not inferred from file.parent.name like ingest_verses.py --
    # that directory is literally "niv" (lowercase), and every downstream
    # query is against the uppercase "NIV" translation code used everywhere
    # else in this app.
    translation: str = "NIV",
) -> None:
    """CLI: ingest jburson/bible-data's word-formatted NIV text into the
    `reading_verses` and `reading_headings` tables.

    Args:
        file: Path to the jburson/bible-data translation JSON
        translation: Translation code to store
    """
    if not file.exists():
        sys.exit(f"File not found: {file}")

    verses, headings = ingest_file(file, translation)
    print(f"Submitted {verses} reading verses and {headings} reading headings for translation {translation!r} (duplicates skipped).")


if __name__ == "__main__":
    tyro.cli(main)
