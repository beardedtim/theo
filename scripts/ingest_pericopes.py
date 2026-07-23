"""CLI: ingest data/pericopes.json into the `pericopes` table.

Usage:
    uv run -m scripts.ingest_pericopes data/pericopes.json
"""

import sys
from pathlib import Path

import tyro

from theo.pericopes import ingest_file


def main(file: tyro.conf.Positional[Path] = Path("data/pericopes.json")) -> None:
    """CLI: ingest data/pericopes.json into the `pericopes` table.

    Args:
        file: Path to the pericopes JSON file
    """
    if not file.exists():
        sys.exit(f"File not found: {file}")

    submitted = ingest_file(file)
    print(f"Submitted {submitted} pericopes (duplicates skipped).")


if __name__ == "__main__":
    tyro.cli(main)
