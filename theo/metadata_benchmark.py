"""LLM/NLP metadata benchmark: score each `pericope_annotations` pipeline's
extracted entities against STEPBible's TIPNR tagging (theo.step_names),
which CLAUDE.md already treats as ground truth for "which proper nouns are
in this passage" -- exhaustive, derived from original-language tagging, not
NER. This gives an automatic entity-extraction Precision/Recall/F1 with no
hand-labeling.

Matching is done on normalized surface-form text, not theo.parse's
`ustrong` gazetteer id: the spaCy pipeline (en_core_web_trf+fastcoref)
populates `ustrong` for its own gazetteer hits, but LLM pipelines never do,
so scoring by id would only ever be fair to spaCy. Ground truth per verse
is expanded to that occurrence's own per-translation spelling (STEP's
canonical "Elimelech" is NIV's "Elimelek", etc.), scoped to the specific
name-form `step_name_verses` ties to that verse -- NOT every form of the
record the way theo.parse._gazetteer_strings does for building its
whole-Bible entity ruler. STEP's unified Strong's numbers group same-entity
spellings across the whole Bible under one record (e.g. Ram's OT Hebrew
form and Luke 3's differing Greek-genealogy renderings "Aram"/"Arni"/
"Admin" share a record), so unioning every form's variants would expect
Luke's Greek spelling to appear in a Ruth 4 genealogy verse that never used
it -- inflating "expected" and tanking recall for reasons having nothing to
do with extraction quality.

There's no equivalent ground truth for the LLM-only `extras` (summary,
themes, keywords, tone, speech_acts) or for SVO triples -- those are
generative, not extractive, and would need a small hand-graded sample or an
LLM-as-judge rubric instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from theo.annotations import get_annotation
from theo.bible import book_number
from theo.db import get_connection
from theo.parse import _NAME_RE
from theo.pericopes import Pericope, list_pericopes
from theo.step_names import TipnrForm, TipnrRecord, parse_tipnr

_ARTICLE_RE = re.compile(r"^(the|a|an)\s+", re.IGNORECASE)


def _normalize(text: str) -> str:
    """Lowercase, strip surrounding punctuation, drop a leading article --
    enough to bridge "the LORD" (LLM phrasing) vs "LORD" (STEP's name)
    without doing any real NLP."""
    text = text.strip().strip(".,;:!?\"'’").lower()
    return _ARTICLE_RE.sub("", text)


def _form_surface_strings(record: TipnrRecord, form: TipnrForm, translation: str) -> set[str]:
    """This form's rendering for `translation` specifically -- TIPNR's
    `translations` field lists spellings per translation code, e.g.
    "Chilion =ESV,KJV; Kilion =NIV" (codes are comma-joined when they share
    a spelling), and NIV text can only ever produce "Kilion", never
    "Chilion". Falls back to the record's canonical name when the field
    doesn't call `translation` out at all (most forms use one spelling
    everywhere and don't bother annotating it). Filtered through theo.parse's
    own proper-noun shape check so junk renderings (lowercase common-word
    translations TIPNR sometimes carries) don't pollute ground truth."""
    names: set[str] = set()
    for segment in (form.translations or "").split(";"):
        name_part, _, codes = segment.strip().partition("=")
        if translation in {c.strip() for c in codes.split(",")}:
            names.add(name_part.strip())
    if not names:
        names.add(record.name)
    return {n for n in names if _NAME_RE.match(n)}


def _load_form_surfaces(translation: str) -> dict[tuple[str, int], set[str]]:
    """(tipnr_key, form_seq) -> that specific form's surface strings under
    `translation`. Keyed per-form, not per-record, so a pericope only gets
    held to the spelling(s) actually tied to its own verses -- see module
    docstring. Requires the raw TIPNR file (data/step-bible/...) to still be
    present, same as theo.parse's gazetteer at annotation time."""
    return {
        (record.tipnr_key, form.seq): _form_surface_strings(record, form, translation)
        for record in parse_tipnr()
        for form in record.forms
    }


def _expected_surface_forms(pericope: Pericope, form_surfaces: dict[tuple[str, int], set[str]]) -> set[str]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT sn.tipnr_key, snf.form_seq
                FROM step_name_verses sv
                JOIN step_names sn ON sn.id = sv.step_name_id
                JOIN step_name_forms snf ON snf.id = sv.form_id
                WHERE sv.book = %s
                    AND (sv.chapt_num, sv.verse_num) >= (%s, %s)
                    AND (sv.chapt_num, sv.verse_num) <= (%s, %s)
                """,
                (pericope.book, pericope.chapter_start, pericope.verse_start, pericope.chapter_end, pericope.verse_end),
            )
            rows = cur.fetchall()

    forms: set[str] = set()
    for tipnr_key, form_seq in rows:
        forms |= {_normalize(f) for f in form_surfaces.get((tipnr_key, form_seq), set())}
    return forms


def list_pipelines() -> list[str]:
    """Every distinct pipeline with stored annotations, e.g.
    "en_core_web_trf+fastcoref/v1", "together:deepseek-ai/DeepSeek-V4-Pro/v1"."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT pipeline FROM pericope_annotations ORDER BY pipeline")
            return [row[0] for row in cur.fetchall()]


@dataclass(frozen=True)
class EntityOutcome:
    pericope_id: str
    pericope_title: str
    expected: set[str]
    extracted: set[str]
    missed: set[str]  # expected - extracted: false negatives
    spurious: set[str]  # extracted - expected: false positives (may be legitimate non-STEP mentions)


@dataclass(frozen=True)
class EntityReport:
    pipeline: str
    n_pericopes: int
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float
    outcomes: list[EntityOutcome]


def evaluate_entities(
    pipeline: str,
    translation: str = "NIV",
    book: int | str | None = None,
    max_pericopes: int | None = None,
) -> EntityReport:
    """Score `pipeline`'s stored entities against STEP ground truth, pooling
    true/false positives/negatives across every pericope (micro-averaged --
    stabler than per-pericope averaging given how many passages have zero or
    one expected name)."""
    book_num = None if book is None else (book if isinstance(book, int) else book_number(book))
    form_surfaces = _load_form_surfaces(translation)
    pericopes = list_pericopes(book_num)
    if max_pericopes is not None:
        pericopes = pericopes[:max_pericopes]

    tp = fp = fn = 0
    outcomes: list[EntityOutcome] = []
    for pericope in pericopes:
        row = get_annotation(pericope.id, translation, pipeline)
        if row is None or row["entities"] is None:
            continue

        expected = _expected_surface_forms(pericope, form_surfaces)
        extracted = {_normalize(e["text"]) for e in row["entities"]}

        matched = expected & extracted
        missed = expected - extracted
        spurious = extracted - expected

        tp += len(matched)
        fn += len(missed)
        fp += len(spurious)
        outcomes.append(
            EntityOutcome(
                pericope_id=pericope.id, pericope_title=pericope.title,
                expected=expected, extracted=extracted, missed=missed, spurious=spurious,
            )
        )

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return EntityReport(
        pipeline=pipeline, n_pericopes=len(outcomes),
        tp=tp, fp=fp, fn=fn, precision=precision, recall=recall, f1=f1, outcomes=outcomes,
    )


def worst(report: EntityReport, by: str = "missed", limit: int = 10) -> list[EntityOutcome]:
    """The `limit` outcomes with the most `by` ("missed" or "spurious")
    entries, non-empty ones only."""
    candidates = [o for o in report.outcomes if getattr(o, by)]
    return sorted(candidates, key=lambda o: len(getattr(o, by)), reverse=True)[:limit]
