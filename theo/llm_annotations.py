"""Batch driver: run the together.ai enrichment (theo.llm_parse) over every
pericope and store the results in `pericope_annotations`, alongside the
local spaCy pipeline's rows under a "together:<model>/v1" pipeline key.

Oversized pericopes (text beyond _SEGMENT_CHAR_BUDGET, where the model's
echoed-back resolved_text would blow the response token limit) are split on
verse boundaries into segments, annotated one request per segment, and
merged back into a single stored row (theo.llm_parse.merge_parsed). A
failure in any segment fails the whole pericope, so a rerun redoes all of
its segments -- the stored row is always complete, never partial.

Unlike theo.annotations' GPU batching, the work here is network-bound, so
the driver fans requests out over a thread pool and commits each result as
it lands -- an interrupted run loses at most the requests in flight, and
rerunning skips everything already stored. A truncated response (a
stochastic repetition loop, see theo.llm_parse.TruncatedResponse) is
retried per _BUDGET_ATTEMPTS before counting as a failure; any other
request/response failure is logged and skipped (not retried within the
run, beyond the HTTP-level retries in theo.llm_parse), so one bad response
can't kill a full-corpus run; rerun to retry just the failures.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from psycopg.types.json import Jsonb
from rich.progress import track

from theo.annotations import annotated_ids
from theo.bible import book_name, get_verses_in_range
from theo.db import get_connection
from theo.llm_parse import (
    DEFAULT_MODEL,
    LlmParsedText,
    TruncatedResponse,
    api_key,
    merge_parsed,
    parse_text,
    pipeline_id,
    set_min_request_interval,
)
from theo.pericopes import Pericope, list_pericopes

logger = logging.getLogger(__name__)

# Per-request text budget. The model must echo the passage back as
# resolved_text plus all the structured fields, so output scales with input;
# ~5k chars (~1,250 tokens) keeps worst-case output far under the request's
# max_tokens. 56 of 2,227 NIV pericopes exceed this (Psalm 119 tops out at
# ~13k chars -> 3 segments); everything else stays a single request.
_SEGMENT_CHAR_BUDGET = 5000


def _pack_verses(texts: list[str], budget: int = _SEGMENT_CHAR_BUDGET) -> list[str]:
    """Greedily pack verse texts into segments of at most ~budget chars,
    splitting only on verse boundaries. A pericope within the budget stays
    one segment (the common case); a single verse longer than the budget
    becomes its own segment rather than being split mid-verse."""
    segments: list[str] = []
    current: list[str] = []
    length = 0
    for text in texts:
        joined = length + len(text) + 1 if current else len(text)
        if current and joined > budget:
            segments.append(" ".join(current))
            current, length = [text], len(text)
        else:
            current.append(text)
            length = joined
    if current:
        segments.append(" ".join(current))
    return segments


# Truncation retry ladder: a truncated response is almost always a
# stochastic repetition loop in an uncapped string field (the schema's
# maxItems caps stop the list-field loops), so the same request usually
# completes on a plain retry; the last-resort attempt halves the segment
# budget, changing the prompts outright.
_BUDGET_ATTEMPTS = (_SEGMENT_CHAR_BUDGET, _SEGMENT_CHAR_BUDGET, _SEGMENT_CHAR_BUDGET // 2)


def _verse_texts(pericope: Pericope, translation: str) -> list[str]:
    verses = get_verses_in_range(
        translation,
        pericope.book,
        pericope.chapter_start,
        pericope.verse_start,
        pericope.chapter_end,
        pericope.verse_end,
    )
    return [v.text for v in verses]


def _enrich(pericope: Pericope, translation: str, model: str) -> LlmParsedText | None:
    """One pericope through the LLM: split into segments, annotate each,
    merge. On a truncated response the whole pericope is retried per
    _BUDGET_ATTEMPTS; the final truncation (or any other failure) raises
    for the driver to log."""
    texts = _verse_texts(pericope, translation)
    if not texts:
        return None
    reference = _reference(pericope)
    for attempt, budget in enumerate(_BUDGET_ATTEMPTS, start=1):
        segments = _pack_verses(texts, budget)
        try:
            parts = [
                parse_text(
                    reference if len(segments) == 1
                    else f"{reference} (part {i} of {len(segments)})",
                    pericope.title,
                    segment,
                    model=model,
                )
                for i, segment in enumerate(segments, start=1)
            ]
            return merge_parsed(parts)
        except TruncatedResponse:
            if attempt == len(_BUDGET_ATTEMPTS):
                raise
            logger.warning(
                "truncated response for %s (%s); retrying (%d/%d, budget %d)",
                pericope.title, pericope.id,
                attempt + 1, len(_BUDGET_ATTEMPTS), _BUDGET_ATTEMPTS[attempt],
            )
    raise AssertionError("unreachable")


def _reference(pericope: Pericope) -> str:
    """Human-readable range, e.g. "Genesis 1:1-2:3" or "Ruth 1:1-22"."""
    book = book_name(pericope.book)
    start = f"{pericope.chapter_start}:{pericope.verse_start}"
    if pericope.chapter_end == pericope.chapter_start:
        return f"{book} {start}-{pericope.verse_end}"
    return f"{book} {start}-{pericope.chapter_end}:{pericope.verse_end}"


def llm_annotate_pericopes(
    translation: str = "NIV",
    book: int | str | None = None,
    limit: int | None = None,
    model: str = DEFAULT_MODEL,
    concurrency: int = 8,
    min_request_interval: float = 0.5,
) -> tuple[int, int]:
    """Enrich every not-yet-annotated pericope through the LLM and store the
    results. Returns (annotated, failed) counts.

    Safe to rerun/resume: pericopes already annotated under this
    translation+pipeline are skipped, and each result is committed as it
    arrives. min_request_interval paces request dispatch across all
    `concurrency` worker threads (seconds between dispatches) so the pool
    doesn't itself trigger together.ai's rate limit by bursting; raise it if
    a run is still hitting 429s, lower it once quota headroom is known.
    """
    pipeline = pipeline_id(model)
    done = annotated_ids(translation, pipeline)
    todo = [p for p in list_pericopes(book) if p.id not in done]
    if limit is not None:
        todo = todo[:limit]
    if todo:
        api_key()  # fail fast on a missing key, not once per dispatched request
        set_min_request_interval(min_request_interval)

    annotated = failed = 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = {pool.submit(_enrich, p, translation, model): p for p in todo}
                try:
                    for future in track(
                        as_completed(futures),
                        total=len(futures),
                        description=f"LLM-annotating {translation} pericopes",
                    ):
                        pericope = futures[future]
                        try:
                            parsed = future.result()
                        except Exception:
                            logger.exception("enrichment failed for %s (%s)", pericope.title, pericope.id)
                            failed += 1
                            continue
                        if parsed is None:
                            continue
                        cur.execute(
                            """
                            INSERT INTO pericope_annotations (
                                pericope_id, translation, pipeline, resolved_text, entities, svo, extras
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (pericope_id, translation, pipeline) DO NOTHING
                            """,
                            (
                                pericope.id,
                                translation,
                                pipeline,
                                parsed.resolved,
                                Jsonb(parsed.entities),
                                Jsonb([list(triple) for triple in parsed.svo]),
                                Jsonb(parsed.extras),
                            ),
                        )
                        conn.commit()
                        annotated += 1
                except BaseException:
                    # A DB failure or Ctrl-C escaping the loop must not strand
                    # the queue: the executor's __exit__ waits for every queued
                    # future and this loop is no longer consuming them, so their
                    # paid API results would be computed and discarded. Cancel
                    # the queue so shutdown waits only for the requests already
                    # in flight (at most `concurrency` of them).
                    pool.shutdown(wait=False, cancel_futures=True)
                    raise
    return annotated, failed
