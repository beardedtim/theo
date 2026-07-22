"""Interface for personal commentary notes: hand-written markdown files
with YAML frontmatter under notes/ (see ingest_notes.py for how they get
into the `notes` table), used to supplement/correct Theographic's more
theologically conservative framing with the user's own research.

Frontmatter fields:
  title (required)  -- str
  book (required)    -- number or name, e.g. "Exodus" or 2
  tags (optional)    -- list of strings, default []
  one of, to anchor the note to a verse range:
    chapter_start/verse_start/chapter_end/verse_end  -- full range
    chapter/verse_start/verse_end                     -- one chapter
    chapter/verse                                     -- a single verse

Everything after the closing `---` is the note body: raw markdown, stored
and served as-is (rendering it is a client concern).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from psycopg.rows import dict_row

from theo.bible import book_number
from theo.bm25 import sanitize_query
from theo.db import get_connection

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?\n)---\s*\n?(.*)\Z", re.DOTALL)

_COLUMNS = "id, slug, title, book, chapter_start, verse_start, chapter_end, verse_end, tags, body"


@dataclass(frozen=True)
class ParsedNote:
    """One notes/*.md file's frontmatter + body, not yet in the database --
    what ingest_notes.py hands to its upsert."""
    slug: str
    title: str
    book: int
    chapter_start: int
    verse_start: int
    chapter_end: int
    verse_end: int
    tags: list[str]
    body: str


@dataclass(frozen=True)
class Note:
    id: str
    slug: str
    title: str
    book: int
    chapter_start: int
    verse_start: int
    chapter_end: int
    verse_end: int
    tags: list[str]
    body: str


def _range_from_frontmatter(fm: dict, path: Path) -> tuple[int, int, int, int]:
    """Accepts three progressively terser range shapes so a hand-written
    note doesn't have to spell out chapter_start/verse_start/chapter_end/
    verse_end for the common case of a single verse or a same-chapter
    range: chapter_start/verse_start/chapter_end/verse_end (full form),
    chapter/verse_start/verse_end (one chapter), or chapter/verse (a single
    verse)."""
    if "chapter_start" in fm:
        return fm["chapter_start"], fm["verse_start"], fm["chapter_end"], fm["verse_end"]
    if "chapter" not in fm:
        raise ValueError(
            f"{path}: frontmatter needs either chapter_start/verse_start/chapter_end/verse_end "
            "or chapter/verse_start/verse_end or chapter/verse"
        )
    chapter = fm["chapter"]
    if "verse_start" in fm:
        return chapter, fm["verse_start"], chapter, fm["verse_end"]
    verse = fm["verse"]
    return chapter, verse, chapter, verse


def parse_note_file(path: Path, slug: str) -> ParsedNote:
    """Parse one notes/*.md file into its frontmatter fields + body. `slug`
    is the note's stable identity (see ingest_notes.py for how it's derived
    from the file's path relative to the notes root) -- not read from the
    file itself, so moving a file changes its slug."""
    text = path.read_text()
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"{path}: missing YAML frontmatter (expected a leading '---' block)")

    fm = yaml.safe_load(match.group(1)) or {}
    body = match.group(2).strip()

    book = fm["book"]
    book_num = book if isinstance(book, int) else book_number(str(book))
    chapter_start, verse_start, chapter_end, verse_end = _range_from_frontmatter(fm, path)

    return ParsedNote(
        slug=slug,
        title=fm["title"],
        book=book_num,
        chapter_start=chapter_start,
        verse_start=verse_start,
        chapter_end=chapter_end,
        verse_end=verse_end,
        tags=[str(t) for t in (fm.get("tags") or [])],
        body=body,
    )


def slug_for(path: Path, notes_dir: Path) -> str:
    """A note's stable identity: its path relative to notes_dir, without
    the .md extension, so notes/exodus/burning-bush.md -> "exodus/burning-bush"."""
    return path.relative_to(notes_dir).with_suffix("").as_posix()


def sync_notes(notes_dir: Path, prune: bool = False) -> tuple[int, int]:
    """Parse every notes_dir/**/*.md file and upsert it into `notes`, keyed
    by slug.

    Safe to rerun after editing, adding, or renaming note files: unlike the
    theographic/STEP ingest scripts (which only ever add rows), this
    treats the folder as the current source of truth for any file present,
    so edits overwrite in place. Deleting a file does NOT delete its row
    unless `prune=True` -- pruning compares against whatever `notes_dir`
    happens to be, so running it against the wrong path (a subset of your
    real notes, a stale checkout, a typo) would silently delete every note
    outside that path. Opt in only when you're syncing your one real notes
    folder and know a file's actually gone missing on purpose. Returns
    (upserted, deleted) counts -- deleted is always 0 when prune=False.
    """
    paths = sorted(notes_dir.rglob("*.md"))
    parsed = [parse_note_file(path, slug_for(path, notes_dir)) for path in paths]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO notes (slug, title, book, chapter_start, verse_start, chapter_end, verse_end, tags, body)
                VALUES (%(slug)s, %(title)s, %(book)s, %(chapter_start)s, %(verse_start)s,
                        %(chapter_end)s, %(verse_end)s, %(tags)s, %(body)s)
                ON CONFLICT (slug) DO UPDATE SET
                    title = EXCLUDED.title,
                    book = EXCLUDED.book,
                    chapter_start = EXCLUDED.chapter_start,
                    verse_start = EXCLUDED.verse_start,
                    chapter_end = EXCLUDED.chapter_end,
                    verse_end = EXCLUDED.verse_end,
                    tags = EXCLUDED.tags,
                    body = EXCLUDED.body
                """,
                [
                    {
                        "slug": n.slug,
                        "title": n.title,
                        "book": n.book,
                        "chapter_start": n.chapter_start,
                        "verse_start": n.verse_start,
                        "chapter_end": n.chapter_end,
                        "verse_end": n.verse_end,
                        "tags": n.tags,
                        "body": n.body,
                    }
                    for n in parsed
                ],
            )

            deleted = 0
            if prune and parsed:
                cur.execute("DELETE FROM notes WHERE NOT (slug = ANY(%s))", ([n.slug for n in parsed],))
                deleted = cur.rowcount
        conn.commit()

    return len(parsed), deleted


# --- Reading notes back out of the table --------------------------------------

def _row_to_note(row: dict) -> Note:
    return Note(
        id=str(row["id"]),
        slug=row["slug"],
        title=row["title"],
        book=row["book"],
        chapter_start=row["chapter_start"],
        verse_start=row["verse_start"],
        chapter_end=row["chapter_end"],
        verse_end=row["verse_end"],
        tags=row["tags"] or [],
        body=row["body"],
    )


def list_notes() -> list[Note]:
    """List every note, in canonical passage order."""
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(f"SELECT {_COLUMNS} FROM notes ORDER BY book, chapter_start, verse_start")
            rows = cur.fetchall()
    return [_row_to_note(row) for row in rows]


def get_notes_in_range(
    book: int | str,
    chapter_start: int,
    verse_start: int,
    chapter_end: int,
    verse_end: int,
) -> list[Note]:
    """Every note overlapping the range, in canonical order. `book` may be
    either its number (1-66) or its name (e.g. "Genesis")."""
    book_num = book if isinstance(book, int) else book_number(book)
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT {_COLUMNS}
                FROM notes
                WHERE book = %s
                    AND (chapter_start, verse_start) <= (%s, %s)
                    AND (chapter_end, verse_end) >= (%s, %s)
                ORDER BY chapter_start, verse_start
                """,
                (book_num, chapter_end, verse_end, chapter_start, verse_start),
            )
            rows = cur.fetchall()
    return [_row_to_note(row) for row in rows]


def get_note(slug: str) -> Note | None:
    """Fetch a single note by its slug, or None if it doesn't exist."""
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(f"SELECT {_COLUMNS} FROM notes WHERE slug = %s", (slug,))
            row = cur.fetchone()
    return _row_to_note(row) if row else None


def search_notes(query: str, limit: int = 50) -> list[Note]:
    """Full-text search over note titles/bodies (BM25), best match first."""
    query = sanitize_query(query)
    if not query:
        return []

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT {_COLUMNS}, paradedb.score(id) AS score
                FROM notes
                WHERE title @@@ %(query)s OR body @@@ %(query)s
                ORDER BY score DESC
                LIMIT %(limit)s
                """,
                {"query": query, "limit": limit},
            )
            rows = cur.fetchall()
    return [_row_to_note(row) for row in rows]
