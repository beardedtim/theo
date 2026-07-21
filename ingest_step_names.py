"""CLI: ingest STEPBible TIPNR proper-noun data into the `step_names`,
`step_name_forms`, and `step_name_verses` tables.

Usage:
    uv run ingest_step_names.py
"""

import sys
from pathlib import Path

import tyro

from theo.step_names import TIPNR_PATH, ingest_file


def main(file: tyro.conf.Positional[Path] = TIPNR_PATH) -> None:
    """CLI: ingest STEPBible TIPNR proper-noun data into the `step_names`,
    `step_name_forms`, and `step_name_verses` tables.

    Args:
        file: Path to STEPBible's TIPNR tab-separated data file
    """
    if not file.exists():
        sys.exit(f"File not found: {file}")

    names, forms, links = ingest_file(file)
    print(f"Submitted {names} names, {forms} name forms, {links} verse links (duplicates skipped).")


if __name__ == "__main__":
    tyro.cli(main)
