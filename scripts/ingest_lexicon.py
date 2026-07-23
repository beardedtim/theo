"""CLI: parse STEPBible's TBESH (Hebrew) and TBESG (Greek) brief lexicons
and load them into the `step_lexicon` table.

Usage:
    uv run -m scripts.ingest_lexicon
"""

import tyro

from theo.lexicon import TBESG_PATH, TBESH_PATH, ingest_file


def main(hebrew: bool = True, greek: bool = True) -> None:
    """CLI: ingest the STEPBible brief Strong's lexicons.

    Args:
        hebrew: Ingest the Hebrew lexicon (TBESH)
        greek: Ingest the Greek lexicon (TBESG)
    """
    if hebrew:
        count = ingest_file(TBESH_PATH, "hebrew")
        print(f"Submitted {count} Hebrew lexicon entries (duplicates skipped).")
    if greek:
        count = ingest_file(TBESG_PATH, "greek")
        print(f"Submitted {count} Greek lexicon entries (duplicates skipped).")


if __name__ == "__main__":
    tyro.cli(main)
