from fastapi import FastAPI, HTTPException, Path, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from theo.bible import Verse, parse_book_id

from theo.bible import (
    get_chapter as fetch_chapter,
    get_verses as fetch_verses,
)

from theo.pericopes import Pericope, PericopeDetail

from theo.pericopes import (
    get_pericope_detail as fetch_pericope_detail,
    list_pericopes as fetch_pericopes,
    search_pericopes as fetch_pericope_search,
)

from theo.people import Person
from theo.people import get_people_in_range as fetch_people_in_range

from theo.places import Place
from theo.places import get_places_in_range as fetch_places_in_range

from theo.events import Event, EventDetail
from theo.events import (
    get_event as fetch_event,
    get_events_in_range as fetch_events_in_range,
    list_events as fetch_events,
)

from theo.people_groups import GroupDetail, PeopleGroup
from theo.people_groups import (
    get_group as fetch_group,
    list_groups as fetch_groups,
)

from theo.passage_groups import PassageGroup, PassageGroupDetail
from theo.passage_groups import (
    get_passage_group_detail as fetch_passage_group_detail,
    list_passage_groups as fetch_passage_groups,
)

from theo.dictionary import DictionaryEntry
from theo.dictionary import (
    get_dictionary_entry as fetch_dictionary_entry,
    search_dictionary as run_dictionary_search,
)

from theo.step_names import StepName, StepNameDetail
from theo.step_names import (
    get_name as fetch_name,
    get_names_in_range as fetch_names_in_range,
    search_names as run_name_search,
)

from theo.lexicon import LexiconEntry
from theo.lexicon import (
    get_lexicon_entries as fetch_lexicon_entries,
    search_lexicon as run_lexicon_search,
)

from theo.notes import Note
from theo.notes import (
    get_note as fetch_note,
    get_notes_in_range as fetch_notes_in_range,
    list_notes as fetch_all_notes,
    search_notes as run_note_search,
)

from theo.metadata import VerseMetadata
from theo.metadata import (
    get_metadata_for_pericope as fetch_metadata_for_pericope,
    get_metadata_for_range as fetch_metadata_for_range,
)

from theo.search import SearchMode, SearchResult
from theo.search import search as run_search
from theo.logger import setup_rich_logger

from theo.reading import ReadingBlock
from theo.reading import get_reading as fetch_reading


def get_app() -> FastAPI:
    app = FastAPI(title="Theo Text Pipeline API")
    origins = [
        "http://localhost:5173",
    ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    setup_rich_logger()

    return app

app = get_app()

@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    # book_number()/book_name() raise ValueError for unrecognized book
    # identifiers -- surface that as a 404 instead of a 500.
    return JSONResponse(status_code=404, content={"detail": str(exc)})

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/verses/{book}/{chapter}/{verse_start}/{verse_end}")
def get_verse_range(
    book: str = Path(..., description='Book number or name, e.g. "1" or "Genesis".'),
    chapter: int = Path(..., description="Chapter number."),
    verse_start: int = Path(..., description="The start of this range"),
    verse_end: int = Path(..., description="The end of this range"),
    translation: str = "NIV",
) -> list[Verse]:
    """Fetch a range of verses from a chapter"""
    verses = fetch_verses(
        translation=translation,
        book=parse_book_id(book),
        chapter=chapter,
        verse_start=verse_start,
        verse_end=verse_end,
    )

    if not verses:
        raise HTTPException(status_code=404, detail="Verse range not found")

    return verses

@app.get("/verses/{book}/{chapter}")
def get_chapter(
    book: str = Path(..., description='Book number or name, e.g. "1" or "Genesis".'),
    chapter: int = Path(..., description="Chapter number."),
    translation: str = "NIV",
) -> list[Verse]:
    """Fetch an entire chapter of verses."""
    verses = fetch_chapter(translation, parse_book_id(book), chapter)

    if not verses:
        raise HTTPException(status_code=404, detail="Chapter not found")

    return verses

@app.get("/pericopes")
def list_pericopes(
    book: str | None = Query(None, description='Optional book filter: number or name, e.g. "1" or "Genesis".'),
    q: str | None = Query(None, description='Optional full-text search over pericope titles, e.g. "prodigal son".'),
) -> list[Pericope]:
    """List pericopes in canonical order. Combine `book` and/or `q` to narrow the list down."""
    book_id = parse_book_id(book) if book else None
    if q:
        return fetch_pericope_search(q, book_id)
    return fetch_pericopes(book_id)

@app.get("/pericopes/{book}")
def get_pericopes_for_book(
    book: str = Path(..., description='Book number or name, e.g. "1" or "Genesis".'),
) -> list[Pericope]:
    """List every pericope in a single book, in canonical order."""
    pericopes = fetch_pericopes(parse_book_id(book))

    if not pericopes:
        raise HTTPException(status_code=404, detail="Book not found")

    return pericopes

@app.get("/pericope/{pericope_id}")
def get_pericope(
    pericope_id: str = Path(..., description="Pericope id, as returned by /pericopes."),
    translation: str = "NIV",
) -> PericopeDetail:
    """Fetch a single pericope along with its full verse text, for reading/studying that passage."""
    detail = fetch_pericope_detail(pericope_id, translation)

    if detail is None:
        raise HTTPException(status_code=404, detail="Pericope not found")

    return detail

@app.get("/people/{book}/{chapter_start}/{verse_start}/{chapter_end}/{verse_end}")
def get_people_for_range(
    book: str = Path(..., description='Book number or name, e.g. "1" or "Genesis".'),
    chapter_start: int = Path(..., description="Chapter the range starts in."),
    verse_start: int = Path(..., description="Verse the range starts at."),
    chapter_end: int = Path(..., description="Chapter the range ends in."),
    verse_end: int = Path(..., description="Verse the range ends at."),
) -> list[Person]:
    """List every person mentioned in a verse range. `chapter_start`/`verse_start`/
    `chapter_end`/`verse_end` match the shape returned by /search and /pericope/{id}
    (a pericope's or search result's book/chapter_start/verse_start/chapter_end/verse_end),
    so the client can look this up right after a search or pericope fetch. An empty
    list just means no named people are mentioned in that range."""
    return fetch_people_in_range(parse_book_id(book), chapter_start, verse_start, chapter_end, verse_end)

@app.get("/places/{book}/{chapter_start}/{verse_start}/{chapter_end}/{verse_end}")
def get_places_for_range(
    book: str = Path(..., description='Book number or name, e.g. "1" or "Genesis".'),
    chapter_start: int = Path(..., description="Chapter the range starts in."),
    verse_start: int = Path(..., description="Verse the range starts at."),
    chapter_end: int = Path(..., description="Chapter the range ends in."),
    verse_end: int = Path(..., description="Verse the range ends at."),
) -> list[Place]:
    """List every place mentioned in a verse range. Same range shape as
    /people/{book}/{chapter_start}/{verse_start}/{chapter_end}/{verse_end}; an empty
    list just means no named places are mentioned in that range."""
    return fetch_places_in_range(parse_book_id(book), chapter_start, verse_start, chapter_end, verse_end)

@app.get("/events")
def list_events() -> list[Event]:
    """List every event in chronological order."""
    return fetch_events()

@app.get("/events/{book}/{chapter_start}/{verse_start}/{chapter_end}/{verse_end}")
def get_events_for_range(
    book: str = Path(..., description='Book number or name, e.g. "1" or "Genesis".'),
    chapter_start: int = Path(..., description="Chapter the range starts in."),
    verse_start: int = Path(..., description="Verse the range starts at."),
    chapter_end: int = Path(..., description="Chapter the range ends in."),
    verse_end: int = Path(..., description="Verse the range ends at."),
) -> list[Event]:
    """List every event mentioned in a verse range. Same range shape as
    /people/{book}/{chapter_start}/{verse_start}/{chapter_end}/{verse_end}; an empty
    list just means no events are tagged to that range."""
    return fetch_events_in_range(parse_book_id(book), chapter_start, verse_start, chapter_end, verse_end)

@app.get("/event/{event_id}")
def get_event(
    event_id: str = Path(..., description="Event id, as returned by /events."),
) -> EventDetail:
    """Fetch a single event along with its resolved participants and locations."""
    detail = fetch_event(event_id)

    if detail is None:
        raise HTTPException(status_code=404, detail="Event not found")

    return detail

@app.get("/people-groups")
def list_people_groups() -> list[PeopleGroup]:
    """List every people group (tribes, apostles, genealogies...)."""
    return fetch_groups()

@app.get("/people-groups/{group_id}")
def get_people_group(
    group_id: str = Path(..., description="Group id, as returned by /people-groups."),
) -> GroupDetail:
    """Fetch a single people group along with its resolved members."""
    detail = fetch_group(group_id)

    if detail is None:
        raise HTTPException(status_code=404, detail="People group not found")

    return detail

@app.get("/passage-groups")
def list_passage_groups() -> list[PassageGroup]:
    """List every canon-structure group (Pentateuch, Old/New Testament,
    Gospels...) -- which books belong together. See theo.passage_groups."""
    return fetch_passage_groups()

@app.get("/passage-groups/{slug}")
def get_passage_group(
    slug: str = Path(..., description='Group slug, name, or alias -- e.g. "pentateuch", "Pentateuch", or "Torah". Matched case-insensitively.'),
) -> PassageGroupDetail:
    """Fetch a single passage group along with its expanded book list, its
    direct child groups, and its aliases. Accepts a slug, canonical name, or
    any alias (see theo.passage_groups.resolve_passage_group)."""
    detail = fetch_passage_group_detail(slug)

    if detail is None:
        raise HTTPException(status_code=404, detail="Passage group not found")

    return detail

@app.get("/dictionary")
def search_dictionary(
    q: str = Query(..., description='Search query, e.g. "phylactery".'),
    limit: int = Query(50, ge=1, le=200, description="Max number of entries to return."),
) -> list[DictionaryEntry]:
    """Search Easton's Bible Dictionary by term or definition text (BM25)."""
    return run_dictionary_search(q, limit=limit)

@app.get("/dictionary/{entry_id}")
def get_dictionary_entry(
    entry_id: str = Path(..., description="Entry id, as returned by /dictionary."),
) -> DictionaryEntry:
    """Fetch a single dictionary entry."""
    entry = fetch_dictionary_entry(entry_id)

    if entry is None:
        raise HTTPException(status_code=404, detail="Dictionary entry not found")

    return entry

@app.get("/names")
def search_step_names(
    q: str = Query(..., description='Search query, e.g. "high priest".'),
    limit: int = Query(50, ge=1, le=200, description="Max number of names to return."),
) -> list[StepName]:
    """Search STEPBible's proper nouns (persons, places, months, deities...)
    by name or description text (BM25)."""
    return run_name_search(q, limit=limit)

@app.get("/names/{book}/{chapter_start}/{verse_start}/{chapter_end}/{verse_end}")
def get_names_for_range(
    book: str = Path(..., description='Book number or name, e.g. "1" or "Genesis".'),
    chapter_start: int = Path(..., description="Chapter the range starts in."),
    verse_start: int = Path(..., description="Verse the range starts at."),
    chapter_end: int = Path(..., description="Chapter the range ends in."),
    verse_end: int = Path(..., description="Verse the range ends at."),
) -> list[StepName]:
    """List every STEPBible proper noun occurring in a verse range. Unlike
    /people and /places (theographic data), these links come from TIPNR's
    original-language tagging, so they are exhaustive per verse. Same range
    shape as /people/{book}/.../{verse_end}; an empty list just means no
    proper nouns occur in that range."""
    return fetch_names_in_range(parse_book_id(book), chapter_start, verse_start, chapter_end, verse_end)

@app.get("/name/{name_id}")
def get_step_name(
    name_id: str = Path(..., description="Name id, as returned by /names."),
) -> StepNameDetail:
    """Fetch a single proper noun with its name forms (Hebrew/Greek script,
    Strong's numbers, per-translation renderings), prose article, and full
    verse reference list."""
    detail = fetch_name(name_id)

    if detail is None:
        raise HTTPException(status_code=404, detail="Name not found")

    return detail

@app.get("/lexicon")
def search_step_lexicon(
    q: str = Query(..., description='Search query, e.g. "steadfast love".'),
    limit: int = Query(50, ge=1, le=200, description="Max number of entries to return."),
) -> list[LexiconEntry]:
    """Search STEPBible's brief Strong's lexicons (Hebrew + Greek) by gloss,
    transliteration, or meaning text (BM25)."""
    return run_lexicon_search(q, limit=limit)

@app.get("/lexicon/{strongs}")
def get_step_lexicon_entries(
    strongs: str = Path(..., description='A Strong\'s number, e.g. "H0175" or "G2264H".'),
) -> list[LexiconEntry]:
    """Every lexicon entry matching a Strong's number, whichever numbering
    system it comes from (dStrong, eStrong, or uStrong). A uStrong -- like
    step_names' `ustrong` or an annotation entity's id -- fans out to all
    the entries unified under it, across both testaments (e.g. H0175 returns
    Hebrew Aaron and its Greek form)."""
    entries = fetch_lexicon_entries(strongs)

    if not entries:
        raise HTTPException(status_code=404, detail="No lexicon entries for that Strong's number")

    return entries

@app.get("/notes")
def search_notes(
    q: str | None = Query(None, description='Search query, e.g. "documentary hypothesis". Omit to list every note.'),
    limit: int = Query(50, ge=1, le=200, description="Max number of notes to return."),
) -> list[Note]:
    """Search personal commentary notes by title or body text (BM25), or --
    if `q` is omitted -- list every note in canonical passage order (for a
    browsable Notes page)."""
    if q is None:
        return fetch_all_notes()
    return run_note_search(q, limit=limit)

@app.get("/notes/{book}/{chapter_start}/{verse_start}/{chapter_end}/{verse_end}")
def get_notes_for_range(
    book: str = Path(..., description='Book number or name, e.g. "1" or "Genesis".'),
    chapter_start: int = Path(..., description="Chapter the range starts in."),
    verse_start: int = Path(..., description="Verse the range starts at."),
    chapter_end: int = Path(..., description="Chapter the range ends in."),
    verse_end: int = Path(..., description="Verse the range ends at."),
) -> list[Note]:
    """List every personal note overlapping a verse range. Same range shape
    as /people/{book}/.../{verse_end}; an empty list just means no note is
    anchored to that range."""
    return fetch_notes_in_range(parse_book_id(book), chapter_start, verse_start, chapter_end, verse_end)

@app.get("/note/{slug:path}")
def get_note(
    slug: str = Path(..., description="Note slug, as returned by /notes (its file path under notes/, without .md)."),
) -> Note:
    """Fetch a single personal note by its slug."""
    note = fetch_note(slug)

    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    return note

@app.get("/metadata/pericope/{pericope_id}")
def get_metadata_by_pericope(
    pericope_id: str = Path(..., description="Pericope id, as returned by /search or /pericopes."),
    translation: str = Query("NIV", description="Translation whose NLP annotations to include."),
) -> VerseMetadata:
    """Everything known about a pericope's verse range in one call: the
    overlapping pericopes, one source-prioritized `entities` list (STEP
    proper nouns first, theographic knowledge graph filling the gaps),
    events, Strong's lexicon entries (keyed by the entities' ustrongs),
    one NLP annotation per pericope (best pipeline: LLM over spaCy), any
    personal notes anchored to the range, the passage groups the book
    belongs to (e.g. Pentateuch), and `attributes` -- key/value facts
    (author, date, ...) inherited from notes on the range or any
    containing passage group, most specific scope winning. The per-source
    endpoints (/people, /names, /notes, /passage-groups, ...) still expose
    everything."""
    metadata = fetch_metadata_for_pericope(pericope_id, translation=translation)

    if metadata is None:
        raise HTTPException(status_code=404, detail="Pericope not found")

    return metadata

@app.get("/metadata/{book}/{chapter_start}/{verse_start}/{chapter_end}/{verse_end}")
def get_metadata_by_range(
    book: str = Path(..., description='Book number or name, e.g. "1" or "Genesis".'),
    chapter_start: int = Path(..., description="Chapter the range starts in."),
    verse_start: int = Path(..., description="Verse the range starts at."),
    chapter_end: int = Path(..., description="Chapter the range ends in."),
    verse_end: int = Path(..., description="Verse the range ends at."),
    translation: str = Query("NIV", description="Translation whose NLP annotations to include."),
) -> VerseMetadata:
    """Everything known about a manual verse range in one call -- same
    payload as /metadata/pericope/{id}, same range shape as /people and
    /reading. One annotation per pericope the range overlaps."""
    return fetch_metadata_for_range(
        parse_book_id(book), chapter_start, verse_start, chapter_end, verse_end,
        translation=translation,
    )

@app.get("/reading/{book}/{chapter_start}/{verse_start}/{chapter_end}/{verse_end}")
def get_reading_view(
    book: str = Path(..., description='Book number or name, e.g. "1" or "Genesis".'),
    chapter_start: int = Path(..., description="Chapter the range starts in."),
    verse_start: int = Path(..., description="Verse the range starts at."),
    chapter_end: int = Path(..., description="Chapter the range ends in."),
    verse_end: int = Path(..., description="Verse the range ends at."),
    translation: str = "NIV",
) -> list[ReadingBlock]:
    """Fetch a verse range laid out for reading: paragraphs, poetry line
    breaks/indentation, section headings, and inline styling (smallcaps,
    italics, bold, red-letter). NIV only for now -- any other translation
    404s. Same range shape as /people/{book}/.../{verse_end} etc."""
    blocks = fetch_reading(translation, parse_book_id(book), chapter_start, verse_start, chapter_end, verse_end)

    if not blocks:
        raise HTTPException(status_code=404, detail="Reading view not found for this range")

    return blocks

@app.get("/search")
def search(
    q: str = Query(..., description='Natural-language query, e.g. "a shepherd caring for lost sheep".'),
    mode: SearchMode = Query(
        "hybrid",
        description='"semantic" (embedding cosine similarity), "bm25" (keyword relevance), '
        'or "hybrid" (both, blended via reciprocal rank fusion).',
    ),
    limit: int = Query(10, ge=1, le=50, description="Max number of pericopes to return."),
    translation: str = "NIV",
) -> list[SearchResult]:
    """Search the Bible for pericopes related to a query, each returned with its full verse text."""
    return run_search(q, mode=mode, translation=translation, limit=limit)