"""Interface for ingesting jburson/bible-data's word-formatted NIV text
(data/info/data/niv/niv.json) into the `reading_verses` and
`reading_headings` tables, and assembling it back into paragraph/poetry-line
structure for the reading view.

Deliberately separate from `theo.bible`/`theo.pericopes` -- those stay the
flat/raw source of truth for search, embeddings, and the theographic
verse-range joins. This module exists purely to answer "how should this
passage be laid out on a page," for NIV only, for now.

Source format (see data/info/README.md and build_pericopes.py, which already
reads this same file to derive pericope boundaries): a flat JSON array of
items shaped `{"o": <order>, "r": "niv:<Book>:<chapter>:<verse>", "t": <text>,
"h"?: <level>}`. Items with `h` are section headings (1 = chapter title,
2/2.5 = section, 3/4 = sub-heading). A verse component of 0 anchors the
heading before the chapter's first verse; any other value reuses the verse
number of the item immediately preceding it in the stream (that verse's text
item already came before the heading), so the heading actually belongs
*after* that verse -- i.e. immediately before the next one. (build_pericopes.py
derives a new pericope's verse_start the same way: from the first verse item
past the heading, not from the heading's own `r`.) Items without `h` are
verse text, where individual words in `t` can carry a `*<codes>` suffix (e.g.
"Blessed*pn") marking paragraph starts (p), new poetry lines at various
indents/alignments (l+one of n/d/e/g/c, or bare n/c paired directly with p),
and inline styling (s smallcaps, i italic, b bold, r red-letter/words-of-Christ).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from theo.bible import BOOK_NUMBERS, book_number
from theo.db import get_connection

# Case-insensitive fallback for spelling differences against our own BOOKS
# list (source has "Song of Solomon", we have "Song Of Solomon") -- mirrors
# build_pericopes.py's local book_number() helper, which solved this exact
# problem against the same source file.
_NORMALIZED_NAMES = {name.lower(): num for name, num in BOOK_NUMBERS.items()}


def _source_book_number(name: str) -> int:
    if name in BOOK_NUMBERS:
        return BOOK_NUMBERS[name]
    return _NORMALIZED_NAMES[name.lower()]


def _parse_word(raw: str) -> dict:
    if "*" not in raw:
        return {"word": raw}
    word, codes = raw.rsplit("*", 1)
    return {"word": word, "codes": codes}


# --- Ingestion ----------------------------------------------------------

def ingest_file(path: Path, translation: str) -> tuple[int, int]:
    """Load a jburson/bible-data translation JSON into `reading_verses` and
    `reading_headings`.

    Safe to rerun: rows already present (by their unique constraints) are
    left alone. Returns (verses submitted, headings submitted) -- not
    necessarily inserted, since duplicates are skipped.
    """
    items = json.loads(Path(path).read_text())

    verse_rows = []
    heading_rows = []
    for item in items:
        _, book_name, chapter_s, verse_s = item["r"].split(":")
        book_num = _source_book_number(book_name)
        chapter, verse = int(chapter_s), int(verse_s)

        if "h" in item:
            heading_rows.append(
                (translation, book_num, chapter, verse, item["o"], item["h"], item["t"])
            )
        else:
            tokens = [_parse_word(w) for w in item["t"].split(" ")]
            verse_rows.append((translation, book_num, chapter, verse, Jsonb(tokens)))

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO reading_verses (translation, book, chapt_num, verse_num, tokens)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (translation, book, chapt_num, verse_num) DO NOTHING
                """,
                verse_rows,
            )
            cur.executemany(
                """
                INSERT INTO reading_headings
                    (translation, book, chapt_num, anchor_verse_num, order_num, level, heading_text)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (translation, book, chapt_num, order_num) DO NOTHING
                """,
                heading_rows,
            )
        conn.commit()

    return len(verse_rows), len(heading_rows)


# --- Response shapes ------------------------------------------------------

@dataclass(frozen=True)
class ReadingRun:
    text: str
    chapter: int | None   # set together with `verse`, only on the run where
    verse: int | None     # a new verse begins -- None on continuation runs
    smallcaps: bool = False
    italic: bool = False
    bold: bool = False
    red_letter: bool = False


@dataclass(frozen=True)
class ReadingLine:
    indent: int   # 0, 1, or 2
    align: str    # "left" | "center" | "right"
    runs: list[ReadingRun]


@dataclass(frozen=True)
class HeadingBlock:
    kind: Literal["heading"]
    level: float
    text: str


@dataclass(frozen=True)
class ParagraphBlock:
    kind: Literal["paragraph"]
    lines: list[ReadingLine]


ReadingBlock = HeadingBlock | ParagraphBlock

# Line-start codes that also set indent/alignment (bare "p" or "l" alone --
# never actually occurs in the NIV file, but is a documented code -- falls
# through to the default left/no-indent below).
_LINE_STYLE: dict[str, tuple[int, str]] = {
    "d": (2, "left"),
    "n": (1, "left"),
    "c": (0, "center"),
    "g": (0, "right"),
    "e": (0, "left"),
}
_BREAK_CODES = "plndcge"


# --- Assembly ---------------------------------------------------------

def assemble_blocks(verse_rows: list[dict], heading_rows: list[dict]) -> list[ReadingBlock]:
    """Pure function: merge raw `reading_verses`/`reading_headings` rows
    (already filtered to a range and ordered by (chapt_num, verse_num) /
    (chapt_num, order_num)) into paragraph/poetry-line/heading blocks.

    Headings are matched to position by (chapt_num, target verse) rather
    than by a SQL range filter on anchor_verse_num -- anchor 0 ("before verse
    1") would otherwise be silently excluded by a naive tuple-range
    comparison whenever verse_start=1, which is the most common query shape.
    anchor_verse_num of 0 targets verse 1; any other anchor targets
    anchor_verse_num + 1, since the source data stores non-zero anchors as
    the verse *before* which the heading's text actually occurred in the
    stream (see module docstring) -- matching the raw anchor verbatim would
    place the heading one verse too early.
    """
    headings_by_anchor: dict[tuple[int, int], list[dict]] = {}
    for h in heading_rows:
        anchor = h["anchor_verse_num"]
        target_verse = 1 if anchor == 0 else anchor + 1
        headings_by_anchor.setdefault((h["chapt_num"], target_verse), []).append(h)
    for group in headings_by_anchor.values():
        group.sort(key=lambda h: h["order_num"])

    blocks: list[ReadingBlock] = []
    para_lines: list[ReadingLine] = []
    line_runs: list[ReadingRun] = []
    line_indent = 0
    line_align = "left"
    run_words: list[str] = []
    run_style = {"smallcaps": False, "italic": False, "bold": False, "red_letter": False}
    run_chapter: int | None = None
    run_verse: int | None = None

    def flush_run() -> None:
        nonlocal run_words, run_chapter, run_verse
        if run_words:
            line_runs.append(
                ReadingRun(text=" ".join(run_words), chapter=run_chapter, verse=run_verse, **run_style)
            )
        run_words = []
        run_chapter = None
        run_verse = None

    def flush_line() -> None:
        nonlocal line_runs, line_indent, line_align
        flush_run()
        if line_runs:
            para_lines.append(ReadingLine(indent=line_indent, align=line_align, runs=line_runs))
        line_runs = []
        line_indent = 0
        line_align = "left"

    def flush_paragraph() -> None:
        nonlocal para_lines
        flush_line()
        if para_lines:
            blocks.append(ParagraphBlock(kind="paragraph", lines=para_lines))
        para_lines = []

    for row in verse_rows:
        chapt_num = row["chapt_num"]
        verse_num = row["verse_num"]

        pending = headings_by_anchor.pop((chapt_num, verse_num), None)
        if pending:
            flush_paragraph()
            for h in pending:
                blocks.append(HeadingBlock(kind="heading", level=h["level"], text=h["heading_text"]))

        for idx, token in enumerate(row["tokens"]):
            word = token["word"]
            codes = token.get("codes", "")
            is_verse_start = idx == 0

            has_break = any(c in codes for c in _BREAK_CODES)
            style = {
                "smallcaps": "s" in codes,
                "italic": "i" in codes,
                "bold": "b" in codes,
                "red_letter": "r" in codes,
            }

            if has_break or is_verse_start or style != run_style:
                flush_run()
                if has_break:
                    flush_line()
                    if "p" in codes:
                        flush_paragraph()
                    indent, align = 0, "left"
                    for code_char, (new_indent, new_align) in _LINE_STYLE.items():
                        if code_char in codes:
                            indent, align = new_indent, new_align
                            break
                    line_indent, line_align = indent, align
                run_style = style
                run_chapter = chapt_num if is_verse_start else None
                run_verse = verse_num if is_verse_start else None

            run_words.append(word)

    flush_paragraph()
    return blocks


def get_reading(
    translation: str,
    book: int | str,
    chapter_start: int,
    verse_start: int,
    chapter_end: int,
    verse_end: int,
) -> list[ReadingBlock]:
    """Fetch the reading-formatted layout for a verse range. `book` may be
    either its number (1-66) or its name (e.g. "Genesis"), same as the rest
    of the app's verse-range endpoints."""
    if translation.upper() != "NIV":
        raise ValueError(f"Reading view not available for translation {translation!r}")

    book_num = book if isinstance(book, int) else book_number(book)
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT chapt_num, verse_num, tokens
                FROM reading_verses
                WHERE translation = %s AND book = %s
                    AND (chapt_num, verse_num) >= (%s, %s)
                    AND (chapt_num, verse_num) <= (%s, %s)
                ORDER BY chapt_num, verse_num
                """,
                (translation.upper(), book_num, chapter_start, verse_start, chapter_end, verse_end),
            )
            verse_rows = cur.fetchall()

            cur.execute(
                """
                SELECT chapt_num, anchor_verse_num, order_num, level, heading_text
                FROM reading_headings
                WHERE translation = %s AND book = %s AND chapt_num BETWEEN %s AND %s
                ORDER BY chapt_num, order_num
                """,
                (translation.upper(), book_num, chapter_start, chapter_end),
            )
            heading_rows = cur.fetchall()

    return assemble_blocks(verse_rows, heading_rows)
