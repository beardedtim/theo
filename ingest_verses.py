"""CLI: ingest a translation's combined verse JSON into the `verses` table.

Usage:
    uv run ingest_verses.py data/bible/NIV/NIV_bible.json --translation NIV
"""

import sys
from pathlib import Path

import tyro

from theo.bible import ingest_file


def main(
    file: tyro.conf.Positional[Path],
    translation: str | None = None,
) -> None:
    """CLI: ingest a translation's combined verse JSON into the `verses` table.

    Args:
        file: Path to the translation's combined verse JSON
        translation: Translation code to store (default: inferred from the parent directory name)
    """
    if not file.exists():
        sys.exit(f"File not found: {file}")

    resolved_translation = translation or file.parent.name
    submitted = ingest_file(file, resolved_translation)
    print(f"Submitted {submitted} verses for translation {resolved_translation!r} (duplicates skipped).")


if __name__ == "__main__":
    tyro.cli(main)
