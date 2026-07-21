"""Interface for reading and writing verse data.

Wraps the raw `data/bible/<CODE>/<CODE>_bible.json` corpora and the `verses`
table, and translates between the table's integer `book` column and human
book names (book 1 <-> "Genesis").
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from psycopg.rows import dict_row

from theo.db import get_connection

# Canonical 66-book order (Protestant canon), 1-indexed to match the `book`
# column in the `verses` table.
BOOKS = [
    "Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy",
    "Joshua", "Judges", "Ruth", "1 Samuel", "2 Samuel",
    "1 Kings", "2 Kings", "1 Chronicles", "2 Chronicles", "Ezra",
    "Nehemiah", "Esther", "Job", "Psalm", "Proverbs",
    "Ecclesiastes", "Song Of Solomon", "Isaiah", "Jeremiah", "Lamentations",
    "Ezekiel", "Daniel", "Hosea", "Joel", "Amos",
    "Obadiah", "Jonah", "Micah", "Nahum", "Habakkuk",
    "Zephaniah", "Haggai", "Zechariah", "Malachi",
    "Matthew", "Mark", "Luke", "John", "Acts",
    "Romans", "1 Corinthians", "2 Corinthians", "Galatians", "Ephesians",
    "Philippians", "Colossians", "1 Thessalonians", "2 Thessalonians",
    "1 Timothy", "2 Timothy", "Titus", "Philemon", "Hebrews",
    "James", "1 Peter", "2 Peter", "1 John", "2 John",
    "3 John", "Jude", "Revelation",
]
BOOK_NUMBERS = {name: num for num, name in enumerate(BOOKS, start=1)}
BOOK_NAMES = {num: name for name, num in BOOK_NUMBERS.items()}


def book_number(name: str) -> int:
    """e.g. "Genesis" -> 1"""
    try:
        return BOOK_NUMBERS[name]
    except KeyError:
        raise ValueError(f"Unrecognized book name {name!r} — add it to BOOKS in {__file__}") from None


def book_name(number: int) -> str:
    """e.g. 1 -> "Genesis" """
    try:
        return BOOK_NAMES[number]
    except KeyError:
        raise ValueError(f"Unrecognized book number {number!r}") from None


def parse_book_id(book: str) -> int | str:
    """Normalize a path/query book identifier: numeric strings become an int
    book number, anything else is passed through as a book name."""
    return int(book) if book.isdigit() else book


@dataclass(frozen=True)
class Verse:
    translation: str
    book: str
    chapter: int
    verse: int
    text: str


# --- Reading the raw source JSON --------------------------------------------

def load_source(path: Path) -> dict:
    """Parse a combined translation JSON, e.g. data/bible/NIV/NIV_bible.json."""
    return json.loads(Path(path).read_text())


def iter_source_verses(bible: dict):
    """Yield (book_name, chapter_num, verse_num, text) from a parsed translation dict."""
    for name in bible:
        if name not in BOOK_NUMBERS:
            raise ValueError(f"Unrecognized book name {name!r} — add it to BOOKS in {__file__}")
        for chapter_num, verses in bible[name].items():
            for verse_num, text in verses.items():
                yield name, int(chapter_num), int(verse_num), text


# --- Writing the source JSON into the verses table --------------------------

def ingest_file(path: Path, translation: str) -> int:
    """Load a combined verse JSON into the `verses` table.

    Safe to rerun: existing (translation, book, chapter, verse) rows are left
    alone. Returns the number of verses submitted (not necessarily inserted,
    since duplicates are skipped).
    """
    bible = load_source(path)
    rows = [
        (text, verse_num, chapter_num, book_number(name), translation)
        for name, chapter_num, verse_num, text in iter_source_verses(bible)
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO verses (raw_text, verse_num, chapt_num, book, translation)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (translation, book, chapt_num, verse_num) DO NOTHING
                """,
                rows,
            )
        conn.commit()

    return len(rows)


# --- Reading verses back out of the table -----------------------------------

def _row_to_verse(row: dict) -> Verse:
    return Verse(
        translation=row["translation"],
        book=book_name(row["book"]),
        chapter=row["chapt_num"],
        verse=row["verse_num"],
        text=row["raw_text"],
    )


def get_chapter(translation: str, book: int | str, chapter: int) -> list[Verse]:
    """Fetch every verse in a chapter, ordered by verse number. `book` may be
    either its number (1-66) or its name (e.g. "Genesis")."""
    book_num = book if isinstance(book, int) else book_number(book)
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT raw_text, verse_num, chapt_num, book, translation
                FROM verses
                WHERE translation = %s AND book = %s AND chapt_num = %s
                ORDER BY verse_num
                """,
                (translation, book_num, chapter),
            )
            rows = cur.fetchall()
    return [_row_to_verse(row) for row in rows]

def get_verses_in_range(
    translation: str,
    book: int | str,
    chapter_start: int,
    verse_start: int,
    chapter_end: int,
    verse_end: int,
) -> list[Verse]:
    """Fetch every verse from (chapter_start, verse_start) to (chapter_end,
    verse_end) inclusive, possibly spanning multiple chapters. Used to read
    the full text of a pericope."""
    book_num = book if isinstance(book, int) else book_number(book)
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT raw_text, verse_num, chapt_num, book, translation
                FROM verses
                WHERE translation = %s AND book = %s
                    AND (chapt_num, verse_num) >= (%s, %s)
                    AND (chapt_num, verse_num) <= (%s, %s)
                ORDER BY chapt_num, verse_num
                """,
                (translation, book_num, chapter_start, verse_start, chapter_end, verse_end),
            )
            rows = cur.fetchall()
    return [_row_to_verse(row) for row in rows]


def get_verses(translation: str, book: int | str, chapter: int, verse_start: int, verse_end: int) -> list[Verse]:
    """Fetches the verse range given of the chapter. Same rules apply to what book can
    be on get_chapter"""
    book_num = book if isinstance(book, int) else book_number(book)
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT raw_text, verse_num, chapt_num, book, translation
                FROM verses
                WHERE translation = %s AND book = %s AND chapt_num = %s
                    AND verse_num >= %s AND verse_num <= %s
                ORDER BY verse_num
                """,
                (translation, book_num, chapter, verse_start, verse_end),
            )
            
            rows = cur.fetchall()
    return [_row_to_verse(row) for row in rows]
