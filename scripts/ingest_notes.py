import sys
from pathlib import Path

import tyro

from theo.notes import sync_notes


def main(dir: tyro.conf.Positional[Path] = Path("notes"), prune: bool = False) -> None:
    """CLI: sync notes/*.md (YAML frontmatter + markdown body) into the
    `notes` table. Safe to rerun any time -- edited files overwrite their
    row, new files insert.

    Args:
        dir: Path to the notes folder to sync.
        prune: Also delete rows whose file is no longer in `dir`. Off by
            default: pruning trusts `dir` to be your *complete* notes
            folder, so running it against a partial path would delete
            every note outside that path. Only pass this when syncing your
            real notes folder and you've actually removed a file from it.
    """
    if not dir.exists():
        sys.exit(f"Directory not found: {dir}")

    upserted, deleted = sync_notes(dir, prune=prune)
    print(f"Upserted {upserted} notes.")
    if deleted:
        print(f"Deleted {deleted} notes no longer present in {dir}.")


if __name__ == "__main__":
    tyro.cli(main)
