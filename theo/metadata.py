"""One-stop metadata assembly for a verse range: everything the database
knows about a passage, gathered from the per-source modules so a client can
make a single call instead of fanning out over /people, /places, /events,
/names, /lexicon, etc.

Where several sources describe the same thing, /metadata returns ONE
prioritized answer rather than parallel per-source lists:

- "Who/what is mentioned" comes as a single `entities` list merged across
  sources in `ENTITY_SOURCES` priority order (STEP/TIPNR first -- it is
  derived from original-language tagging -- with the theographic knowledge
  graph filling in anything STEP doesn't name). The merge is per-entity:
  when two sources know the same (kind, name), the higher-priority source's
  record wins; entities only a lower-priority source knows still appear.
- NLP output comes as ONE annotation per pericope, the best available
  pipeline per `ANNOTATION_PIPELINES` (LLM enrichment first, spaCy as the
  fallback).

To promote a new, better source later: add its loader/prefix at the front
of the relevant priority tuple -- everything below it automatically becomes
a fallback. The full unprioritized data stays reachable through the
per-source endpoints (/people, /places, /names, ...).

The client addresses a passage either by a pericope id (the shape /search
results come in) or by a manual (book, chapter/verse range); both funnel
into the same range assembly -- the pericope form just resolves its stored
range first and is guaranteed to include that pericope's own NLP annotation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable

from theo.annotations import get_annotations
from theo.bible import book_number
from theo.events import Event, get_events_in_range
from theo.lexicon import LexiconEntry, get_lexicon_for_ustrongs
from theo.notes import Note, get_notes_in_range
from theo.people import get_people_in_range
from theo.people_groups import get_groups_in_range
from theo.pericopes import Pericope, get_pericope, get_pericopes_in_range
from theo.places import get_places_in_range
from theo.step_names import get_names_in_range

# NLP pipeline priority, highest first: the first prefix that matches any of
# a pericope's stored annotation rows wins; among rows matching the same
# prefix the lexicographically greatest pipeline id is used (a /v2 reprocess
# beats its /v1 predecessor). Rows matching no prefix rank last.
ANNOTATION_PIPELINES: tuple[str, ...] = (
    "together:",     # LLM enrichment (theo.llm_parse) -- has extras
    "en_core_web",   # local spaCy pipeline (theo.parse)
)

Span = tuple[int, int, int, int, int]  # book, chapter/verse start, chapter/verse end


@dataclass(frozen=True)
class Entity:
    """One mentioned person/place/group/thing, source-prioritized. The
    common fields are what list views need; `data` is the source-native
    record (a serialized StepName, Person, Place, or PeopleGroup) for
    detail views."""
    name: str
    kind: str              # "person" | "place" | "group" | "other"
    source: str            # "step" | "theographic"
    description: str | None
    ustrong: str | None    # STEP only: keys into VerseMetadata.lexicon
    data: dict


def _step_kind(category: str, entity_type: str | None) -> str:
    if category == "person":
        return "group" if entity_type == "Group" else "person"
    if category == "place":
        return "place"
    return "other"


def _step_entities(span: Span) -> list[tuple[str, Entity]]:
    return [
        (
            name.name,
            Entity(
                name=name.name,
                kind=_step_kind(name.category, name.entity_type),
                source="step",
                description=name.brief or name.description,
                ustrong=name.ustrong,
                data=asdict(name),
            ),
        )
        for name in get_names_in_range(*span)
    ]


def _theographic_entities(span: Span) -> list[tuple[str, Entity]]:
    entities: list[tuple[str, Entity]] = []
    for person in get_people_in_range(*span):
        entities.append((
            person.name,
            Entity(
                name=person.display_title,
                kind="person",
                source="theographic",
                description=person.dictionary_text,
                ustrong=None,
                data=asdict(person),
            ),
        ))
    for place in get_places_in_range(*span):
        entities.append((
            place.kjv_name,
            Entity(
                name=place.display_title,
                kind="place",
                source="theographic",
                description=place.dictionary_text,
                ustrong=None,
                data=asdict(place),
            ),
        ))
    for group in get_groups_in_range(*span):
        entities.append((
            group.group_name,
            Entity(
                name=group.group_name,
                kind="group",
                source="theographic",
                description=None,
                ustrong=None,
                data=asdict(group),
            ),
        ))
    return entities


# Entity sources, highest priority first. Each loader yields
# (match_name, Entity) pairs -- match_name is the source's plain/undecorated
# name for the entity, so "Judah" (STEP) shadows "Judah (son of Jacob)"
# (theographic display title) via the underlying name they share.
EntityLoader = Callable[[Span], list[tuple[str, Entity]]]

ENTITY_SOURCES: tuple[tuple[str, EntityLoader], ...] = (
    ("step", _step_entities),
    ("theographic", _theographic_entities),
)


def merge_entities(span: Span) -> list[Entity]:
    """All sources' entities for the range, deduplicated per-entity by
    (kind, case-folded name): the first source in ENTITY_SOURCES to mention
    an entity provides its record. Public because theo.metadata_index reuses
    it too, so the metadata search index names exactly what /metadata
    reports for a pericope."""
    merged: list[Entity] = []
    seen: set[tuple[str, str]] = set()
    for _, loader in ENTITY_SOURCES:
        for match_name, entity in loader(span):
            key = (entity.kind, match_name.casefold())
            if key not in seen:
                seen.add(key)
                merged.append(entity)
    return merged


@dataclass(frozen=True)
class PericopeAnnotation:
    """One pericope's best stored NLP output (see theo.annotations): a
    pericope can carry a row per pipeline (local spaCy, together.ai LLM),
    and /metadata returns only the highest-priority one."""
    pericope_id: str
    translation: str
    pipeline: str
    resolved_text: str | None
    entities: list[dict]           # [{"text","label","start","end","ustrong"}, ...]
    svo: list[list[str]]           # [["subject","verb-lemma","object"], ...]
    extras: dict | None            # LLM-only: {"summary","genre","themes","keywords",
                                   # "tone","speech_acts"}; None for spaCy rows


def _pipeline_rank(pipeline: str) -> int:
    for rank, prefix in enumerate(ANNOTATION_PIPELINES):
        if pipeline.startswith(prefix):
            return rank
    return len(ANNOTATION_PIPELINES)


def best_annotation(pericope_id: str, translation: str) -> PericopeAnnotation | None:
    """A pericope's single best-pipeline NLP annotation (see
    ANNOTATION_PIPELINES). Public because theo.metadata_index reuses it to
    pull the same SVO/entities/themes/keywords/summary /metadata reports."""
    rows = get_annotations(pericope_id, translation)
    if not rows:
        return None
    best_rank = min(_pipeline_rank(row["pipeline"]) for row in rows)
    row = max(
        (r for r in rows if _pipeline_rank(r["pipeline"]) == best_rank),
        key=lambda r: r["pipeline"],
    )
    return PericopeAnnotation(
        pericope_id=str(row["pericope_id"]),
        translation=row["translation"],
        pipeline=row["pipeline"],
        resolved_text=row["resolved_text"],
        entities=row["entities"] or [],
        svo=row["svo"] or [],
        extras=row["extras"],
    )


@dataclass(frozen=True)
class VerseMetadata:
    book: int
    chapter_start: int
    verse_start: int
    chapter_end: int
    verse_end: int
    pericopes: list[Pericope]      # every pericope overlapping the range
    entities: list[Entity]         # everyone/everything mentioned, source-prioritized
    events: list[Event]            # theographic timeline (no competing source yet)
    lexicon: dict[str, list[LexiconEntry]]  # keyed by the entities' ustrong ids
    annotations: list[PericopeAnnotation]   # one per overlapping pericope (best pipeline)
    notes: list[Note]              # personal commentary overlapping the range (see theo.notes)


def get_metadata_for_range(
    book: int | str,
    chapter_start: int,
    verse_start: int,
    chapter_end: int,
    verse_end: int,
    translation: str = "NIV",
) -> VerseMetadata:
    """Everything known about a verse range. `book` may be either its
    number (1-66) or its name (e.g. "Genesis"); `translation` only affects
    which NLP annotations are returned (the rest of the metadata is
    translation-independent)."""
    book_num = book if isinstance(book, int) else book_number(book)
    span: Span = (book_num, chapter_start, verse_start, chapter_end, verse_end)
    pericopes = get_pericopes_in_range(*span)
    entities = merge_entities(span)
    annotations = [
        annotation
        for p in pericopes
        if (annotation := best_annotation(p.id, translation)) is not None
    ]
    return VerseMetadata(
        book=book_num,
        chapter_start=chapter_start,
        verse_start=verse_start,
        chapter_end=chapter_end,
        verse_end=verse_end,
        pericopes=pericopes,
        entities=entities,
        events=get_events_in_range(*span),
        lexicon=get_lexicon_for_ustrongs(
            sorted({e.ustrong for e in entities if e.ustrong})
        ),
        annotations=annotations,
        notes=get_notes_in_range(*span),
    )


def get_metadata_for_pericope(
    pericope_id: str,
    translation: str = "NIV",
) -> VerseMetadata | None:
    """Everything known about a pericope's verse range, or None if the
    pericope doesn't exist. The pericope itself is included in `pericopes`
    (alongside any neighbours its range happens to touch)."""
    pericope = get_pericope(pericope_id)
    if pericope is None:
        return None
    return get_metadata_for_range(
        pericope.book,
        pericope.chapter_start,
        pericope.verse_start,
        pericope.chapter_end,
        pericope.verse_end,
        translation=translation,
    )
