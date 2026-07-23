import sys
from pathlib import Path

import tyro

from theo.passage_groups import sync_passage_groups


def main(path: tyro.conf.Positional[Path] = Path("passage_groups.yaml"), prune: bool = False) -> None:
    """CLI: sync passage_groups.yaml (the canon-structure taxonomy) into the
    `passage_groups`/`passage_group_members` tables. Safe to rerun any time
    -- edits overwrite in place.

    Args:
        path: Path to the passage groups YAML file.
        prune: Also delete group rows whose slug is no longer in the file.
            Off by default -- pruning trusts `path` to be your complete
            taxonomy, so running it against a partial file would delete
            every group missing from it.
    """
    if not path.exists():
        sys.exit(f"File not found: {path}")

    upserted, deleted = sync_passage_groups(path, prune=prune)
    print(f"Upserted {upserted} passage groups.")
    if deleted:
        print(f"Deleted {deleted} passage groups no longer present in {path}.")


if __name__ == "__main__":
    tyro.cli(main)
