"""Interface for parsing and ingesting STEPBible's brief Strong's lexicons
(data/step-bible/Lexicons/TBESH & TBESG) into the `step_lexicon` table.

Unlike TIPNR (theo.step_names), these files are flat TSVs: after a prose
preamble, every line starting with H/G + digit is one entry of exactly 8
tab-separated fields:

    eStrong | dStrong-and-relation | uStrong | original | translit | morph | gloss | meaning

Format facts worth knowing (verified against the 2026 files):
- The Greek preamble embeds TIPNR-style example records ("$========== ..."
  Herod blocks) as documentation, and its field docs continue *below* the
  first data lines' region ends -- neither starts with G+digit, so the
  line-shape filter skips them naturally.
- The dStrong field is "<code> = [relation]", e.g. "H0038 = a Name of";
  the relation says how this entry maps onto the uStrong field's entry
  ("a Name of", "in Aramaic of", "the Greek of", ...). Plain "=" means the
  entry stands for itself.
- The uStrong field is usually a bare code but can carry a composition
  ("H9007 (H9007+H9005)"), a stray trailing comma ("H2438H, "), or a
  lowercase disambiguator ("H2148w") -- the first token, trailing
  punctuation stripped, is the code; the raw field is kept when it says
  more than that.
- dStrong is unique across both files, so it is the natural key.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from psycopg.rows import dict_row

from theo.db import get_connection

LEXICON_DIR = Path(__file__).parent.parent / "data" / "step-bible" / "Lexicons"
TBESH_PATH = LEXICON_DIR / "TBESH - Translators Brief lexicon of Extended Strongs for Hebrew - STEPBible.org CC BY.txt"
TBESG_PATH = LEXICON_DIR / "TBESG - Translators Brief lexicon of Extended Strongs for Greek - STEPBible.org CC BY.txt"

_CODE_RE = re.compile(r"^[HG]\d{4,5}[A-Za-z]?$")
# A data line: Strong's code, tab, rest. Anything else (preamble prose,
# embedded TIPNR examples, blank padding) is ignored.
_DATA_LINE_RE = re.compile(r"^[HG]\d")


@dataclass(frozen=True)
class LexiconEntry:
    dstrong: str
    estrong: str
    ustrong: str
    ustrong_raw: str | None   # source uStrong field, only when it said more than the code
    relation: str | None      # "a Name of", "in Aramaic of", ...; None for plain "="
    language: str             # "hebrew" | "greek"
    original: str | None      # Hebrew/Greek script lemma
    transliteration: str | None
    morph: str | None
    gloss: str | None
    meaning_html: str | None


def _clean(field: str) -> str | None:
    field = field.strip()
    return field or None


def _parse_dstrong(field: str) -> tuple[str, str | None]:
    """Split "H0038 = a Name of" into ("H0038", "a Name of")."""
    code, sep, relation = field.partition(" =")
    code = code.strip()
    if not sep or not _CODE_RE.match(code):
        raise ValueError(f"Unparseable dStrong field {field!r}")
    return code, _clean(relation)


def _parse_ustrong(field: str) -> tuple[str, str | None]:
    """Extract the code from the uStrong field, keeping the raw field when
    it carried extra information (compound composition, extra codes)."""
    raw = field.strip().rstrip(",")
    code = raw.split()[0].rstrip(",")
    if not _CODE_RE.match(code):
        raise ValueError(f"Unparseable uStrong field {field!r}")
    return code, raw if raw != code else None


def parse_lexicon(path: Path, language: str) -> list[LexiconEntry]:
    """Parse one TBESH/TBESG file into LexiconEntry rows, in file order.
    Fails loudly on lines that look like data but don't parse."""
    entries = []
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            if not _DATA_LINE_RE.match(line):
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) != 8:
                raise ValueError(f"Expected 8 fields, got {len(fields)}: {line!r}")
            estrong, dstrong_field, ustrong_field, original, translit, morph, gloss, meaning = fields
            estrong = estrong.strip()
            if not _CODE_RE.match(estrong):
                raise ValueError(f"Unparseable eStrong {estrong!r}")
            dstrong, relation = _parse_dstrong(dstrong_field)
            ustrong, ustrong_raw = _parse_ustrong(ustrong_field)
            entries.append(LexiconEntry(
                dstrong=dstrong,
                estrong=estrong,
                ustrong=ustrong,
                ustrong_raw=ustrong_raw,
                relation=relation,
                language=language,
                original=_clean(original),
                transliteration=_clean(translit),
                morph=_clean(morph),
                gloss=_clean(gloss),
                meaning_html=_clean(meaning),
            ))
    return entries


def ingest_file(path: Path, language: str) -> int:
    """Load one lexicon file into `step_lexicon`.

    Safe to rerun: an entry already present with the same dstrong is left
    alone. Returns the number of entries submitted (not necessarily
    inserted, since duplicates are skipped).
    """
    entries = parse_lexicon(path, language)
    rows = [
        (e.dstrong, e.estrong, e.ustrong, e.ustrong_raw, e.relation,
         e.language, e.original, e.transliteration, e.morph, e.gloss, e.meaning_html)
        for e in entries
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO step_lexicon (
                    dstrong, estrong, ustrong, ustrong_raw, relation,
                    language, original, transliteration, morph, gloss, meaning_html
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (dstrong) DO NOTHING
                """,
                rows,
            )
        conn.commit()

    return len(rows)


# --- Reading entries back out of the table ------------------------------------

_COLUMNS = """dstrong, estrong, ustrong, ustrong_raw, relation,
              language, original, transliteration, morph, gloss, meaning_html"""


def _row_to_entry(row: dict) -> LexiconEntry:
    return LexiconEntry(**row)


def get_lexicon_entries(strongs: str) -> list[LexiconEntry]:
    """Every entry matching a Strong's number, whichever numbering system it
    comes from (dStrong, eStrong, or uStrong) -- a uStrong like TIPNR's
    `step_names.ustrong` or an annotation entity id fans out to all the
    dStrong sub-entries unified under it. Ordered by dstrong."""
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT {_COLUMNS}
                FROM step_lexicon
                WHERE dstrong = %(s)s OR estrong = %(s)s OR ustrong = %(s)s
                ORDER BY dstrong
                """,
                {"s": strongs},
            )
            rows = cur.fetchall()
    return [_row_to_entry(row) for row in rows]


def get_lexicon_for_ustrongs(ustrongs: list[str]) -> dict[str, list[LexiconEntry]]:
    """Batch lookup: entries grouped by uStrong, for linking a set of
    step_names/annotation ids to their lexicon entries in one query. Codes
    with no entries (e.g. TIPNR's G0000 placeholders) are simply absent
    from the result."""
    if not ustrongs:
        return {}
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT {_COLUMNS}
                FROM step_lexicon
                WHERE ustrong = ANY(%s)
                ORDER BY ustrong, dstrong
                """,
                (ustrongs,),
            )
            rows = cur.fetchall()
    grouped: dict[str, list[LexiconEntry]] = {}
    for row in rows:
        grouped.setdefault(row["ustrong"], []).append(_row_to_entry(row))
    return grouped


def search_lexicon(query: str, limit: int = 50) -> list[LexiconEntry]:
    """Full-text search over glosses, transliterations, and meanings (BM25),
    best match first."""
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT {_COLUMNS}, paradedb.score(id) AS score
                FROM step_lexicon
                WHERE gloss @@@ %(query)s
                   OR transliteration @@@ %(query)s
                   OR meaning_html @@@ %(query)s
                ORDER BY score DESC
                LIMIT %(limit)s
                """,
                {"query": query, "limit": limit},
            )
            rows = cur.fetchall()
    return [_row_to_entry({k: v for k, v in row.items() if k != "score"}) for row in rows]
