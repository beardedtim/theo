"""Builds `pericope_metadata_index`, theo.search's third BM25 ranking leg:
one denormalized search-text row per pericope, assembled from the same
sources theo.metadata's /metadata endpoint reports (STEP/TIPNR entities,
theographic entities, and the pericope's best NLP annotation) but that
chunks_<dim>'s raw-verse-text BM25 index never sees.

Without this, a query only matches a pericope when the query's words
literally occur in that translation's verse wording. A search for "Aaron"
still works today because his name is usually in the text -- but a search
for "high priest" misses Exodus 4:14 (Aaron is only named "Aaron the
Levite" there; "high priest" is STEP's description of him), and a search
for "Zion's vindication" misses Isaiah 62 unless that exact phrase happens
to appear verbatim, even though it's the pericope's own LLM-extracted SVO
triple. Indexing entity names/descriptions and SVO/theme/keyword text
alongside the verse text closes that gap.

Theographic entity descriptions are deliberately excluded: `dictionary_text`
is a full Easton's Dictionary entry (thousands of characters), identical
across every pericope that mentions the same person/place, and would
swamp the index. STEP's `brief`/`description` fields are curated
one-liners (~40 chars average) and safe to include in full. Personal notes
(theo.notes) contribute their `title`/`tags` only, for the same reason --
a note's `body` is free-form prose that can run to thousands of characters
and, for a note anchored to a wide range (e.g. a note spanning several
chapters), would repeat in full across every pericope in that range. The
note itself is already reachable in full via `/notes` and `/note/{slug}`.
"""

from __future__ import annotations

from rich.progress import track

from theo.db import get_connection
from theo.metadata import Entity, Span, best_annotation, merge_entities
from theo.notes import get_notes_in_range
from theo.pericopes import Pericope, list_pericopes

# LLM-generated SVO triples use one of these (case-insensitively) as the
# object of an intransitive verb ("the LORD keep silent none") -- a
# placeholder for "no object", not a searchable word. Filtering them out
# keeps a near-universal token out of the index.
_NULL_OBJECT_TOKENS = {"", "none", "n/a", "null", "nothing", "-"}


def _entity_text(entity: Entity) -> list[str]:
    parts = [entity.name]
    if entity.source == "step" and entity.description:
        parts.append(entity.description)
    return parts


def _svo_text(svo: list[list[str]]) -> str | None:
    phrases = []
    for triple in svo:
        subject, verb, *rest = (*triple, "", "")[:3]
        obj = rest[0] if rest and rest[0].strip().lower() not in _NULL_OBJECT_TOKENS else ""
        words = [w for w in (subject, verb, obj) if w]
        if words:
            phrases.append(" ".join(words))
    return "; ".join(phrases) or None


def build_search_text(pericope: Pericope, translation: str = "NIV") -> str:
    """Assemble one pericope's metadata search text: its entities (STEP +
    theographic, source-prioritized and deduplicated the same way
    /metadata reports them) plus its best-pipeline NLP annotation --
    extracted entities, SVO triples, and (LLM pipeline only) themes,
    keywords, and summary."""
    span: Span = (pericope.book, pericope.chapter_start, pericope.verse_start, pericope.chapter_end, pericope.verse_end)
    parts: list[str] = []

    for entity in merge_entities(span):
        parts.extend(_entity_text(entity))

    for note in get_notes_in_range(*span):
        parts.append(note.title)
        parts.extend(note.tags)

    annotation = best_annotation(pericope.id, translation)
    if annotation is not None:
        parts.extend(e["text"] for e in annotation.entities if e.get("text"))
        if svo_text := _svo_text(annotation.svo):
            parts.append(svo_text)
        if annotation.extras:
            parts.extend(annotation.extras.get("themes") or [])
            parts.extend(annotation.extras.get("keywords") or [])
            if summary := annotation.extras.get("summary"):
                parts.append(summary)

    # dict.fromkeys dedupes while keeping first-seen order -- the same
    # entity commonly appears in both the STEP/theographic list and the
    # NLP pipeline's own entity extraction.
    return " | ".join(dict.fromkeys(p.strip() for p in parts if p and p.strip()))


def index_pericopes(translation: str = "NIV", book: int | str | None = None) -> int:
    """(Re)build pericope_metadata_index for every pericope (or one book).

    Safe to rerun: upserts by (pericope_id, translation), so a rerun after
    new STEP/theographic ingestion or a re-annotation just refreshes the
    text. Pericopes with nothing to index (no entities, no annotation) are
    left out entirely rather than stored as an empty row. Returns the
    number of rows written.
    """
    pericopes = list_pericopes(book)
    rows = [
        (p.id, translation, text)
        for p in track(pericopes, description=f"Indexing {translation} pericope metadata")
        if (text := build_search_text(p, translation))
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO pericope_metadata_index (pericope_id, translation, search_text)
                VALUES (%s, %s, %s)
                ON CONFLICT (pericope_id, translation) DO UPDATE SET search_text = EXCLUDED.search_text
                """,
                rows,
            )
        conn.commit()
    return len(rows)
