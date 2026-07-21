"""Build data/pericopes.json from NIV section headings.

Source: the jburson/bible-data NIV dump (cloned into data/info), which tags
each heading with a level (`h`): 1 = chapter number, 2 / 2.5 = a real section
heading, 3 / 4 = finer sub-headings (acrostic stanza labels, psalm
attributions). We split on levels 1/2/2.5 and treat 3/4 as annotations that
stay inside the enclosing section, which keeps pericopes at roughly
"passage" granularity instead of paragraph- or word-level.

A handful of verses have their text interrupted by a heading mid-verse (e.g.
Genesis 29:14). Since the `verses` table stores one row per whole verse, such
a verse can't be split across two pericopes, so it's kept with the section
that started before the heading.

Usage:
    uv run build_pericopes.py
"""

import json
from pathlib import Path

from theo.bible import BOOK_NUMBERS

SOURCE = Path("data/info/data/niv/niv.json")
OUTPUT = Path("data/pericopes.json")

# Case-insensitive fallback for spelling differences against our own BOOKS
# list (e.g. source has "Song of Solomon", we have "Song Of Solomon").
_NORMALIZED_NAMES = {name.lower(): num for name, num in BOOK_NUMBERS.items()}


def book_number(name: str) -> int:
    if name in BOOK_NUMBERS:
        return BOOK_NUMBERS[name]
    return _NORMALIZED_NAMES[name.lower()]


def build_pericopes(items: list[dict]) -> list[dict]:
    pericopes = []
    pending_title = None
    current = None
    prev_book_name = None

    for it in items:
        _, book_name, chapter_s, verse_s = it["r"].split(":")
        chapter, verse = int(chapter_s), int(verse_s)

        if "h" in it:
            if it["h"] <= 2.5:
                pending_title = it["t"]
            continue  # header items carry no verse text of their own

        pos = (chapter, verse)
        same_book = book_name == prev_book_name

        if same_book and current is not None and pos <= (current["chapter_end"], current["verse_end"]):
            # Same verse already claimed by `current` (split mid-verse by a
            # heading) -- keep it there; pending_title still applies next.
            continue

        if pending_title is not None or not same_book:
            if current is not None:
                pericopes.append(current)
            current = {
                "title": pending_title or f"{book_name} {chapter}",
                "book": book_number(book_name),
                "book_name": book_name,
                "chapter_start": chapter,
                "verse_start": verse,
                "chapter_end": chapter,
                "verse_end": verse,
            }
            pending_title = None
        else:
            current["chapter_end"] = chapter
            current["verse_end"] = verse
        prev_book_name = book_name

    if current is not None:
        pericopes.append(current)

    return pericopes


def main():
    items = json.loads(SOURCE.read_text())
    pericopes = build_pericopes(items)

    books_seen = {p["book"] for p in pericopes}
    missing = set(BOOK_NUMBERS.values()) - books_seen
    if missing:
        raise SystemExit(f"missing books in output: {missing}")

    OUTPUT.write_text(json.dumps(pericopes, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {len(pericopes)} pericopes covering all 66 books to {OUTPUT}")


if __name__ == "__main__":
    main()
