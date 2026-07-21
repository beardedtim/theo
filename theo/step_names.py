"""Interface for ingesting STEPBible's TIPNR proper-noun data
(data/step-bible/Proper Nouns/TIPNR - Translators Individualised Proper
Names with all References - STEPBible.org CC BY.txt) into the `step_names`,
`step_name_forms`, and `step_name_verses` tables.

TIPNR gives every proper noun in the Bible (persons, places, months,
deities, ...) a unique Strong's-derived id (uStrong), lists every name form
it appears under (Hebrew/Greek script, disambiguated Strong's numbers,
per-translation renderings), and an exhaustive per-verse occurrence list
derived from the original-language tagging -- ground truth for "which named
entities are in this verse", no NER required.

File format (verified against the file; its preamble documents it):
- Records are separated by "$========== PERSON(s)|PLACE|OTHER" lines. The
  documentation block near the top contains lookalike separators without
  the space after "==========", so parsing keys on the spaced form.
- A record's first line is a tab-separated header row; its first field is
  "Name@firstRef=uStrong", unique across the file and used as the
  idempotency key (uStrong alone is NOT assumed unique here).
- Sub-record lines start with an en-dash "–" (not a tab) and describe one
  name form plus its full reference list. "– Total" roll-ups are derivable
  from the other sub-records and skipped.
- "@Briefest=/@Brief=/@Short=/@Article=" lines carry prose descriptions
  (AI-generated, per the file's own preamble -- the refs embedded in that
  prose contain typos, so only the sub-records' refs field is trusted).
- Every line is padded with trailing tabs (spreadsheet-export artifact).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from psycopg.rows import dict_row

from theo.bm25 import sanitize_query
from theo.db import get_connection

TIPNR_PATH = Path(
    "data/step-bible/Proper Nouns/"
    "TIPNR - Translators Individualised Proper Names with all References - STEPBible.org CC BY.txt"
)

# TIPNR's 3-letter book codes -> Theo's canonical book numbers
# (theo.bible.BOOKS order). "Jam" is a source-data alias for James, which
# also appears as "Jas".
TIPNR_BOOK_CODES = {
    "Gen": 1, "Exo": 2, "Lev": 3, "Num": 4, "Deu": 5,
    "Jos": 6, "Jdg": 7, "Rut": 8, "1Sa": 9, "2Sa": 10,
    "1Ki": 11, "2Ki": 12, "1Ch": 13, "2Ch": 14, "Ezr": 15,
    "Neh": 16, "Est": 17, "Job": 18, "Psa": 19, "Pro": 20,
    "Ecc": 21, "Sng": 22, "Isa": 23, "Jer": 24, "Lam": 25,
    "Ezk": 26, "Dan": 27, "Hos": 28, "Jol": 29, "Amo": 30,
    "Oba": 31, "Jon": 32, "Mic": 33, "Nam": 34, "Hab": 35,
    "Zep": 36, "Hag": 37, "Zec": 38, "Mal": 39,
    "Mat": 40, "Mrk": 41, "Luk": 42, "Jhn": 43, "Act": 44,
    "Rom": 45, "1Co": 46, "2Co": 47, "Gal": 48, "Eph": 49,
    "Php": 50, "Col": 51, "1Th": 52, "2Th": 53,
    "1Ti": 54, "2Ti": 55, "Tit": 56, "Phm": 57, "Heb": 58,
    "Jas": 59, "Jam": 59, "1Pe": 60, "2Pe": 61, "1Jn": 62, "2Jn": 63,
    "3Jn": 64, "Jud": 65, "Rev": 66,
}

_SEPARATOR_PREFIX = "$========== "
_SUBRECORD_PREFIX = "–"  # en-dash
_REF_RE = re.compile(r"^([123]?[A-Za-z]{2,3})\.(\d{1,3})\.(\d{1,3})([a-z]?)(?:\(\?\))?$")
_GMAPS_RE = re.compile(r"@(-?\d+\.\d+),(-?\d+\.\d+)")
_DESC_TAGS = {"Briefest": "briefest", "Brief": "brief", "Short": "short_desc", "Article": "article_html"}


# --- Parsed-file records ------------------------------------------------------

@dataclass(frozen=True)
class TipnrRef:
    book: int
    chapter: int
    verse: int
    occurrence: str = ""  # "a"/"b"/... when a form occurs multiple times in one verse


@dataclass(frozen=True)
class TipnrForm:
    seq: int
    significance: str          # Named, Greek, Spelled, Mentioned, Group, ...
    unique_name: str | None
    strongs_raw: str | None    # e.g. "H0175«H0175=אַהֲרֹן", may be "+"-compound
    dstrong: str | None
    estrong: str | None
    original: str | None       # Hebrew/Greek script (first compound segment)
    translations: str | None   # e.g. "Ebron =ESV; Abdon =NIV; Hebron =KJV"
    refs: tuple[TipnrRef, ...]


@dataclass(frozen=True)
class TipnrRecord:
    tipnr_key: str             # full "Name@firstRef=uStrong" header field
    ustrong: str
    name: str
    category: str              # person | place | other
    entity_type: str | None    # Male, Female, Place, Supernatural, Time, ...
    description: str | None
    parents: str | None
    siblings: str | None
    partners: str | None
    offspring: str | None
    tribe: str | None
    openbible_name: str | None
    founder: str | None
    inhabitants: str | None
    geo_area: str | None
    latitude: float | None
    longitude: float | None
    summary_html: str | None
    briefest: str | None
    brief: str | None
    short_desc: str | None
    article_html: str | None
    forms: tuple[TipnrForm, ...]


def _clean(field: str | None) -> str | None:
    """Normalize a header field: strip padding, treat the source's
    placeholder values ("", ">", bare "+") as absent."""
    if field is None:
        return None
    field = field.strip()
    return field if field not in ("", ">", "+") else None


def _parse_ref(token: str) -> TipnrRef:
    """One "Bok.C.V[a]" token -> TipnrRef. Raises on anything unrecognized
    rather than silently dropping data."""
    m = _REF_RE.match(token)
    if not m:
        raise ValueError(f"Unparseable TIPNR verse ref {token!r}")
    code, chapter, verse, occurrence = m.groups()
    if code not in TIPNR_BOOK_CODES:
        raise ValueError(f"Unknown TIPNR book code {code!r} in ref {token!r}")
    return TipnrRef(TIPNR_BOOK_CODES[code], int(chapter), int(verse), occurrence)


def _parse_ref_field(field: str) -> tuple[TipnrRef, ...]:
    """A sub-record's semicolon-separated refs field -> TipnrRefs. Skips
    empty tokens, LXX-only refs (outside the 66-book versification), and the
    LORD record's "etc" (the one entity whose ref list the source abbreviates).
    "[Act.26.7]" brackets mean present in the original-language tagging but
    bracketed out of the translation -- still a real occurrence."""
    refs: list[TipnrRef] = []
    for token in field.split(";"):
        token = token.strip().strip("[]")
        if not token or token == "etc" or token.startswith("LXX"):
            continue
        # One source token (Joshua's "Num.13.8,16") abbreviates verses
        # of the same chapter with commas -- expand it.
        first, *more_verses = token.split(",")
        ref = _parse_ref(first.strip())
        refs.append(ref)
        refs.extend(
            TipnrRef(ref.book, ref.chapter, int(v.strip()))
            for v in more_verses
        )
    return tuple(refs)


def _parse_strongs(raw: str | None) -> tuple[str | None, str | None, str | None]:
    """"dStrong«eStrong=script[+...]" -> (dstrong, estrong, script) of the
    first compound segment; the full raw string is stored alongside."""
    if not raw:
        return None, None, None
    first = raw.split("+")[0]
    dstrong, _, rest = first.partition("«")
    estrong, _, original = rest.partition("=")
    return _clean(dstrong), _clean(estrong), _clean(original)


def _category(separator_line: str) -> str:
    """Separator -> category. "$========== EXCLUDED OTHER" (12 language
    records like Latin/Aramaic that the source excludes from its lexicon
    extraction) are deliberately kept here as ordinary "other" entities."""
    for marker, category in (("PERSON", "person"), ("PLACE", "place"), ("OTHER", "other")):
        if marker in separator_line:
            return category
    raise ValueError(f"Unrecognized TIPNR record separator {separator_line!r}")


def _iter_records(path: Path):
    """Yield (category, [record lines]) groups. A record's lines are
    contiguous: parsing starts at each "$========== " separator and stops at
    the first blank line, which skips both the file's preamble (before any
    real separator) and the documentation footer trailing the last record."""
    category: str | None = None
    buf: list[str] = []
    with open(path, encoding="utf-8-sig") as fh:
        for raw in fh:
            line = raw.rstrip("\n\r\t ")
            if line.startswith(_SEPARATOR_PREFIX):
                if category is not None and buf:
                    yield category, buf
                category = _category(line)
                buf = []
            elif category is not None:
                if line:
                    buf.append(line)
                elif buf:
                    yield category, buf
                    buf = []
                    category = None
    if category is not None and buf:
        yield category, buf


def _parse_record(category: str, lines: list[str]) -> TipnrRecord:
    fields = [f.strip() for f in lines[0].split("\t")]

    name_field = fields[0]
    if "=" not in name_field:
        raise ValueError(f"TIPNR header without uStrong: {lines[0]!r}")
    ustrong = name_field.rsplit("=", 1)[1]
    name = name_field.split("@", 1)[0]

    # The summary field is marked with a leading "#", except the LORD record
    # where the source typo'd it as "3" -- fall back to spotting its markup.
    summary_idx = next(
        (i for i, f in enumerate(fields) if f.startswith("#") or "<strong=" in f or "<ref=" in f),
        len(fields),
    )
    summary_html = fields[summary_idx].lstrip("#").strip() or None if summary_idx < len(fields) else None
    entity_type = next((f for f in fields[summary_idx + 1:] if f.strip()), None)

    def field(i: int) -> str | None:
        return _clean(fields[i]) if i < summary_idx else None

    parents = siblings = partners = offspring = tribe = None
    openbible_name = founder = inhabitants = geo_area = None
    latitude = longitude = None
    description = field(1)
    if category == "person":
        parents, siblings, partners, offspring, tribe = (field(i) for i in range(2, 7))
    elif category == "place":
        description = None
        openbible_name, founder, inhabitants = field(1), field(2), field(3)
        geo_area = field(6)
        if coords := _GMAPS_RE.search(fields[4] if 4 < summary_idx else ""):
            latitude, longitude = float(coords.group(1)), float(coords.group(2))

    forms: list[TipnrForm] = []
    descriptions: dict[str, str] = {}
    active_tag: str | None = None
    for line in lines[1:]:
        line = line.strip()  # some description lines carry stray leading spaces
        if line.startswith(_SUBRECORD_PREFIX):
            active_tag = None
            sub = [f.strip() for f in line.split("\t")]
            significance = sub[0].lstrip(_SUBRECORD_PREFIX).strip()
            if significance == "Total":
                continue  # roll-up of the other sub-records; nothing unique
            strongs_raw = _clean(sub[2]) if len(sub) > 2 else None
            dstrong, estrong, original = _parse_strongs(strongs_raw)
            refs = _parse_ref_field(sub[5] if len(sub) > 5 else "")
            forms.append(TipnrForm(
                seq=len(forms),
                significance=significance,
                unique_name=_clean(sub[1]) if len(sub) > 1 else None,
                strongs_raw=strongs_raw,
                dstrong=dstrong,
                estrong=estrong,
                original=original,
                translations=_clean(sub[3]) if len(sub) > 3 else None,
                refs=refs,
            ))
        elif line.startswith("@"):
            tag, _, value = line[1:].partition("=")
            active_tag = _DESC_TAGS.get(tag.strip())
            if active_tag is not None:
                descriptions[active_tag] = value.strip()
        elif active_tag is not None:
            # Long @Article prose occasionally wraps onto a bare line.
            descriptions[active_tag] += "\n" + line.strip()
        else:
            raise ValueError(f"Unexpected line in TIPNR record {name_field!r}: {line!r}")

    return TipnrRecord(
        tipnr_key=name_field,
        ustrong=ustrong,
        name=name,
        category=category,
        entity_type=entity_type,
        description=description,
        parents=parents,
        siblings=siblings,
        partners=partners,
        offspring=offspring,
        tribe=tribe,
        openbible_name=openbible_name,
        founder=founder,
        inhabitants=inhabitants,
        geo_area=geo_area,
        latitude=latitude,
        longitude=longitude,
        summary_html=summary_html,
        briefest=descriptions.get("briefest") or None,
        brief=descriptions.get("brief") or None,
        short_desc=descriptions.get("short_desc") or None,
        article_html=descriptions.get("article_html") or None,
        forms=tuple(forms),
    )


def parse_tipnr(path: Path = TIPNR_PATH) -> list[TipnrRecord]:
    """Parse the whole TIPNR file into structured records."""
    return [_parse_record(category, lines) for category, lines in _iter_records(path)]


def verse_entity_lookup(records: list[TipnrRecord]) -> dict[tuple[int, int, int], list[TipnrRecord]]:
    """(book, chapter, verse) -> the entities occurring in that verse,
    deduplicated. The gazetteer view of the data, for NLP enrichment."""
    lookup: dict[tuple[int, int, int], list[TipnrRecord]] = {}
    for record in records:
        seen: set[tuple[int, int, int]] = set()
        for form in record.forms:
            for ref in form.refs:
                coord = (ref.book, ref.chapter, ref.verse)
                if coord not in seen:
                    seen.add(coord)
                    lookup.setdefault(coord, []).append(record)
    return lookup


# --- Ingestion ----------------------------------------------------------------

def ingest_file(path: Path = TIPNR_PATH) -> tuple[int, int, int]:
    """Load the TIPNR file into `step_names`, `step_name_forms`, and
    `step_name_verses`.

    Safe to rerun: rows already present under the same natural key
    (tipnr_key / form_seq / verse coordinates) are left alone. Returns
    (names, forms, verse links) submitted -- not necessarily inserted,
    since duplicates are skipped.
    """
    records = parse_tipnr(path)

    name_rows = [
        (
            r.tipnr_key, r.ustrong, r.name, r.category, r.entity_type, r.description,
            r.parents, r.siblings, r.partners, r.offspring, r.tribe,
            r.openbible_name, r.founder, r.inhabitants, r.geo_area, r.latitude, r.longitude,
            r.summary_html, r.briefest, r.brief, r.short_desc, r.article_html,
        )
        for r in records
    ]
    form_rows = [
        (f.seq, f.significance, f.unique_name, f.strongs_raw, f.dstrong, f.estrong,
         f.original, f.translations, r.tipnr_key)
        for r in records
        for f in r.forms
    ]
    verse_rows = [
        (ref.book, ref.chapter, ref.verse, ref.occurrence, r.tipnr_key, f.seq)
        for r in records
        for f in r.forms
        for ref in f.refs
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO step_names (
                    tipnr_key, ustrong, name, category, entity_type, description,
                    parents, siblings, partners, offspring, tribe,
                    openbible_name, founder, inhabitants, geo_area, latitude, longitude,
                    summary_html, briefest, brief, short_desc, article_html
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tipnr_key) DO NOTHING
                """,
                name_rows,
            )
            cur.executemany(
                """
                INSERT INTO step_name_forms (
                    step_name_id, form_seq, significance, unique_name, strongs_raw,
                    dstrong, estrong, original, translations
                )
                SELECT id, %s, %s, %s, %s, %s, %s, %s, %s
                FROM step_names WHERE tipnr_key = %s
                ON CONFLICT (step_name_id, form_seq) DO NOTHING
                """,
                [(seq, sig, un, sr, ds, es, orig, tr, key)
                 for (seq, sig, un, sr, ds, es, orig, tr, key) in form_rows],
            )
            cur.executemany(
                """
                INSERT INTO step_name_verses (step_name_id, form_id, book, chapt_num, verse_num, occurrence)
                SELECT f.step_name_id, f.id, %s, %s, %s, %s
                FROM step_name_forms f
                JOIN step_names sn ON sn.id = f.step_name_id
                WHERE sn.tipnr_key = %s AND f.form_seq = %s
                ON CONFLICT (form_id, book, chapt_num, verse_num, occurrence) DO NOTHING
                """,
                verse_rows,
            )
        conn.commit()

    return len(name_rows), len(form_rows), len(verse_rows)


# --- Reading names back out of the tables -------------------------------------

@dataclass(frozen=True)
class StepName:
    id: str
    ustrong: str
    name: str
    category: str
    entity_type: str | None
    description: str | None
    brief: str | None


@dataclass(frozen=True)
class StepNameForm:
    significance: str
    unique_name: str | None
    dstrong: str | None
    estrong: str | None
    original: str | None
    translations: str | None


@dataclass(frozen=True)
class StepNameRef:
    book: int
    chapt_num: int
    verse_num: int


@dataclass(frozen=True)
class StepNameDetail:
    id: str
    ustrong: str
    name: str
    category: str
    entity_type: str | None
    description: str | None
    parents: str | None
    siblings: str | None
    partners: str | None
    offspring: str | None
    tribe: str | None
    openbible_name: str | None
    founder: str | None
    inhabitants: str | None
    geo_area: str | None
    latitude: float | None
    longitude: float | None
    summary_html: str | None
    briefest: str | None
    brief: str | None
    short_desc: str | None
    article_html: str | None
    forms: list[StepNameForm]
    refs: list[StepNameRef]


def _row_to_name(row: dict) -> StepName:
    return StepName(
        id=str(row["id"]),
        ustrong=row["ustrong"],
        name=row["name"],
        category=row["category"],
        entity_type=row["entity_type"],
        description=row["description"],
        brief=row["brief"],
    )


def get_names_in_range(
    book: int | str,
    chapter_start: int,
    verse_start: int,
    chapter_end: int,
    verse_end: int,
) -> list[StepName]:
    """Fetch every TIPNR proper noun occurring anywhere in the range,
    deduplicated. Same range shape as theo.places.get_places_in_range.
    `book` may be either its number (1-66) or its name (e.g. "Genesis")."""
    from theo.bible import book_number

    book_num = book if isinstance(book, int) else book_number(book)
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT DISTINCT sn.id, sn.ustrong, sn.name, sn.category, sn.entity_type,
                    sn.description, sn.brief
                FROM step_names sn
                JOIN step_name_verses sv ON sv.step_name_id = sn.id
                WHERE sv.book = %s
                    AND (sv.chapt_num, sv.verse_num) >= (%s, %s)
                    AND (sv.chapt_num, sv.verse_num) <= (%s, %s)
                ORDER BY sn.name
                """,
                (book_num, chapter_start, verse_start, chapter_end, verse_end),
            )
            rows = cur.fetchall()
    return [_row_to_name(row) for row in rows]


def search_names(query: str, limit: int = 50) -> list[StepName]:
    """Full-text search over names and their descriptions/articles (BM25),
    best match first."""
    query = sanitize_query(query)
    if not query:
        return []

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, ustrong, name, category, entity_type, description, brief,
                    paradedb.score(id) AS score
                FROM step_names
                WHERE name @@@ %(query)s OR description @@@ %(query)s
                    OR short_desc @@@ %(query)s OR article_html @@@ %(query)s
                ORDER BY score DESC
                LIMIT %(limit)s
                """,
                {"query": query, "limit": limit},
            )
            rows = cur.fetchall()
    return [_row_to_name(row) for row in rows]


def get_name(name_id: str) -> StepNameDetail | None:
    """Fetch a single proper noun with its name forms and full (deduplicated)
    verse reference list, or None if it doesn't exist."""
    try:
        uuid.UUID(name_id)
    except ValueError:
        return None
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM step_names WHERE id = %s", (name_id,))
            row = cur.fetchone()
            if row is None:
                return None
            cur.execute(
                """
                SELECT significance, unique_name, dstrong, estrong, original, translations
                FROM step_name_forms WHERE step_name_id = %s ORDER BY form_seq
                """,
                (name_id,),
            )
            forms = cur.fetchall()
            cur.execute(
                """
                SELECT DISTINCT book, chapt_num, verse_num
                FROM step_name_verses WHERE step_name_id = %s
                ORDER BY book, chapt_num, verse_num
                """,
                (name_id,),
            )
            refs = cur.fetchall()
    return StepNameDetail(
        id=str(row["id"]),
        ustrong=row["ustrong"],
        name=row["name"],
        category=row["category"],
        entity_type=row["entity_type"],
        description=row["description"],
        parents=row["parents"],
        siblings=row["siblings"],
        partners=row["partners"],
        offspring=row["offspring"],
        tribe=row["tribe"],
        openbible_name=row["openbible_name"],
        founder=row["founder"],
        inhabitants=row["inhabitants"],
        geo_area=row["geo_area"],
        latitude=row["latitude"],
        longitude=row["longitude"],
        summary_html=row["summary_html"],
        briefest=row["briefest"],
        brief=row["brief"],
        short_desc=row["short_desc"],
        article_html=row["article_html"],
        forms=[StepNameForm(**f) for f in forms],
        refs=[StepNameRef(**r) for r in refs],
    )
