"""CLI: scaffold a new notes/*.md file (YAML frontmatter + markdown body,
see theo/notes.py) at a given path under notes/, so starting a note is
"fill in the body" instead of "remember the frontmatter shape."

Doesn't touch the database -- it only writes a file. Run ingest_notes.py
afterward (or `task` picks it up via whatever syncs notes) to load it.

Usage:
    uv run -m scripts.new_note exodus/red-sea-crossing --title "..." --book Exodus \
        --chapter-start 14 --verse-start 1 --chapter-end 14 --verse-end 31

    uv run -m scripts.new_note pentateuch/sources --title "..." --group pentateuch
"""

import sys
from pathlib import Path

import tyro
import yaml

from theo.bible import book_number

PASSAGE_GROUPS_PATH = Path("passage_groups.yaml")

TEMPLATE = """\
---
title: "{title}"
{scope}
tags: [{tags}]
# attributes:
#   some-key: "A short claim, inherited by anything inside this note's scope."
---

TODO: write the note.
"""


def _slug_for(path: str, notes_dir: Path) -> str:
    """Accepts a bare slug ("exodus/foo"), a slug with .md ("exodus/foo.md"),
    or a path already prefixed with notes_dir ("notes/exodus/foo.md") and
    normalizes all three to the bare slug notes.py's slug_for would derive
    once the file exists."""
    p = Path(path)
    parts = p.parts
    if parts[: len(notes_dir.parts)] == notes_dir.parts:
        p = Path(*parts[len(notes_dir.parts):])
    if p.suffix == ".md":
        p = p.with_suffix("")
    if not p.parts or ".." in p.parts:
        sys.exit(f"Invalid notes path: {path!r}")
    return p.as_posix()


def _known_group_slugs(path: Path) -> set[str]:
    if not path.exists():
        return set()
    data = yaml.safe_load(path.read_text()) or {}
    return {g["slug"] for g in data.get("groups", [])}


def main(
    path: tyro.conf.Positional[str],
    title: str,
    book: str | None = None,
    chapter_start: int | None = None,
    verse_start: int | None = None,
    chapter_end: int | None = None,
    verse_end: int | None = None,
    group: str | None = None,
    tags: tuple[str, ...] = (),
    notes_dir: Path = Path("notes"),
) -> None:
    """CLI: scaffold a new note file under notes_dir.

    Args:
        path: Where to create the note, relative to notes_dir -- e.g.
            "exodus/red-sea-crossing" (a bare .md is added automatically).
        title: The note's title (frontmatter `title`).
        book: Book name or number to scope the note to, e.g. "Exodus" or 2.
            Exactly one of book or group is required. Requires
            chapter_start/verse_start/chapter_end/verse_end.
        chapter_start: First chapter of the note's verse range (book scope only).
        verse_start: First verse of the note's verse range (book scope only).
        chapter_end: Last chapter of the note's verse range (book scope only).
        verse_end: Last verse of the note's verse range (book scope only).
        group: A passage_groups.yaml slug to scope the note to instead of a
            book/range, e.g. "pentateuch". Exactly one of book or group is
            required.
        tags: Zero or more free-text tags for the note.
        notes_dir: Root the note path is relative to.
    """
    if (book is None) == (group is None):
        sys.exit("Pass exactly one of --book or --group.")

    if book is not None:
        range_fields = {
            "chapter_start": chapter_start,
            "verse_start": verse_start,
            "chapter_end": chapter_end,
            "verse_end": verse_end,
        }
        missing = [name.replace("_", "-") for name, value in range_fields.items() if value is None]
        if missing:
            sys.exit(f"--book requires {', '.join(f'--{n}' for n in missing)}.")
        if not book.isdigit():
            try:
                book_number(book)
            except ValueError as e:
                sys.exit(str(e))
        scope = (
            f"book: {book}\n"
            f"chapter_start: {chapter_start}\n"
            f"verse_start: {verse_start}\n"
            f"chapter_end: {chapter_end}\n"
            f"verse_end: {verse_end}"
        )
    else:
        known = _known_group_slugs(PASSAGE_GROUPS_PATH)
        if known and group not in known:
            sys.exit(f"Unknown passage group slug {group!r} -- check {PASSAGE_GROUPS_PATH}.")
        scope = f"group: {group}"

    slug = _slug_for(path, notes_dir)
    out_path = (notes_dir / slug).with_suffix(".md")
    if out_path.exists():
        sys.exit(f"{out_path} already exists -- refusing to overwrite.")

    content = TEMPLATE.format(title=title, scope=scope, tags=", ".join(tags))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content)
    print(f"Created {out_path}.")


if __name__ == "__main__":
    tyro.cli(main)
