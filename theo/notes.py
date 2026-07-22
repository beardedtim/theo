"""Interface for personal commentary notes: hand-written markdown files
with YAML frontmatter under notes/ (see ingest_notes.py for how they get
into the `notes` table), used to supplement/correct Theographic's more
theologically conservative framing with the user's own research.

Frontmatter fields:
  title (required)      -- str
  tags (optional)        -- list of strings, default []
  attributes (optional)  -- dict of str -> str, e.g. {author: "Disputed..."};
                             inherited by anything inside the note's scope,
                             see theo.metadata.resolve_attributes
  scope: exactly one of --
    book (+ a range shape below) -- number or name, e.g. "Exodus" or 2, plus
      one of, to anchor the note to a verse range:
        chapter_start/verse_start/chapter_end/verse_end  -- full range
        chapter/verse_start/verse_end                     -- one chapter
        chapter/verse                                     -- a single verse
    group -- a theo.passage_groups slug, e.g. "pentateuch", to anchor the
      note to a whole passage group instead of a specific range

Everything after the closing `---` is the note body: raw markdown, stored
and served as-is (rendering it is a client concern).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from theo.bible import book_number
from theo.bm25 import sanitize_query
from theo.db import get_connection

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?\n)---\s*\n?(.*)\Z", re.DOTALL)

_COLUMNS = (
    "id, slug, title, book, chapter_start, verse_start, chapter_end, verse_end, "
    "passage_group_id, tags, attributes, body"
)


@dataclass(frozen=True)
class ParsedNote:
    """One notes/*.md file's frontmatter + body, not yet in the database --
    what ingest_notes.py hands to its upsert. Exactly one of (book +
    range) or passage_group_slug is set, matching the `notes` table's
    notes_scope_xor constraint."""
    slug: str
    title: str
    book: int | None
    chapter_start: int | None
    verse_start: int | None
    chapter_end: int | None
    verse_end: int | None
    passage_group_slug: str | None
    tags: list[str]
    attributes: dict[str, str]
    body: str


@dataclass(frozen=True)
class Note:
    id: str
    slug: str
    title: str
    book: int | None
    chapter_start: int | None
    verse_start: int | None
    chapter_end: int | None
    verse_end: int | None
    passage_group_id: str | None
    tags: list[str]
    attributes: dict[str, str]
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

    if "group" in fm and "book" in fm:
        raise ValueError(f"{path}: frontmatter has both 'group' and 'book' -- a note is scoped to one or the other")

    if "group" in fm:
        book_num = chapter_start = verse_start = chapter_end = verse_end = None
        passage_group_slug = str(fm["group"])
    else:
        book = fm["book"]
        book_num = book if isinstance(book, int) else book_number(str(book))
        chapter_start, verse_start, chapter_end, verse_end = _range_from_frontmatter(fm, path)
        passage_group_slug = None

    return ParsedNote(
        slug=slug,
        title=fm["title"],
        book=book_num,
        chapter_start=chapter_start,
        verse_start=verse_start,
        chapter_end=chapter_end,
        verse_end=verse_end,
        passage_group_slug=passage_group_slug,
        tags=[str(t) for t in (fm.get("tags") or [])],
        attributes={str(k): str(v) for k, v in (fm.get("attributes") or {}).items()},
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
            cur.execute("SELECT slug, id FROM passage_groups")
            group_slug_to_id = {row[0]: row[1] for row in cur.fetchall()}

            unknown_groups = {
                n.passage_group_slug for n in parsed
                if n.passage_group_slug is not None and n.passage_group_slug not in group_slug_to_id
            }
            if unknown_groups:
                raise ValueError(
                    f"Unknown passage group slug(s) {sorted(unknown_groups)} -- "
                    "check passage_groups.yaml (and rerun ingest_passage_groups.py if you just added them)"
                )

            cur.executemany(
                """
                INSERT INTO notes (
                    slug, title, book, chapter_start, verse_start, chapter_end, verse_end,
                    passage_group_id, tags, attributes, body
                )
                VALUES (
                    %(slug)s, %(title)s, %(book)s, %(chapter_start)s, %(verse_start)s,
                    %(chapter_end)s, %(verse_end)s, %(passage_group_id)s, %(tags)s, %(attributes)s, %(body)s
                )
                ON CONFLICT (slug) DO UPDATE SET
                    title = EXCLUDED.title,
                    book = EXCLUDED.book,
                    chapter_start = EXCLUDED.chapter_start,
                    verse_start = EXCLUDED.verse_start,
                    chapter_end = EXCLUDED.chapter_end,
                    verse_end = EXCLUDED.verse_end,
                    passage_group_id = EXCLUDED.passage_group_id,
                    tags = EXCLUDED.tags,
                    attributes = EXCLUDED.attributes,
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
                        "passage_group_id": group_slug_to_id[n.passage_group_slug] if n.passage_group_slug else None,
                        "tags": n.tags,
                        "attributes": Jsonb(n.attributes),
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
        passage_group_id=str(row["passage_group_id"]) if row["passage_group_id"] else None,
        tags=row["tags"] or [],
        attributes=row["attributes"] or {},
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


def get_notes_for_group(slug: str) -> list[Note]:
    """Every note scoped directly to the passage group `slug` (not its
    ancestors/descendants -- see theo.metadata.resolve_attributes for the
    walk that climbs passage_groups.get_passage_groups_for_book)."""
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT {_COLUMNS}
                FROM notes
                WHERE passage_group_id = (SELECT id FROM passage_groups WHERE slug = %s)
                """,
                (slug,),
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
