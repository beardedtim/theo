"""Interface for storing NLP annotations (theo.parse output) per pericope
in the `pericope_annotations` table, and reading them back.

The pericope is the processing unit because coref and SVO need multi-verse
context. Rows are keyed on (pericope, translation, pipeline) so a reprocess
under a bumped theo.parse.PIPELINE_VERSION coexists with old rows instead of
clobbering them.
"""

from __future__ import annotations

from dataclasses import asdict

import torch
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from rich.progress import track

from theo.chunks import _chunk_text
from theo.db import get_connection
from theo.parse import PIPELINE_VERSION, parse_texts
from theo.pericopes import list_pericopes

_BATCH_SIZE = 16


def _parse_batch(texts: list[str]):
    """parse_texts with an OOM fallback: coref attention memory scales with
    sequence length squared, so a batch of unusually long pericopes can blow
    the GPU -- retry those one text at a time. A single text that still OOMs
    raises, rather than being silently skipped."""
    try:
        return parse_texts(texts)
    except torch.OutOfMemoryError:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        return [parsed for text in texts for parsed in parse_texts([text])]


def annotated_ids(translation: str, pipeline: str) -> set[str]:
    """Pericope ids already annotated under this translation+pipeline --
    what resumable batch drivers (here and theo.llm_annotations) skip."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pericope_id FROM pericope_annotations WHERE translation = %s AND pipeline = %s",
                (translation, pipeline),
            )
            return {str(row[0]) for row in cur.fetchall()}


def annotate_pericopes(
    translation: str = "NIV",
    book: int | str | None = None,
    limit: int | None = None,
) -> int:
    """Run the theo.parse pipeline over every not-yet-annotated pericope and
    store the results.

    Safe to rerun/resume: pericopes already annotated under this
    translation+PIPELINE_VERSION are skipped, and results are committed
    batch by batch, so an interrupted run loses at most the batch in
    flight. Returns the number of pericopes annotated.
    """
    done = annotated_ids(translation, PIPELINE_VERSION)
    todo = [p for p in list_pericopes(book) if p.id not in done]
    if limit is not None:
        todo = todo[:limit]

    annotated = 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            for start in track(
                range(0, len(todo), _BATCH_SIZE),
                description=f"Annotating {translation} pericopes",
            ):
                batch = todo[start:start + _BATCH_SIZE]
                keep = [
                    (pericope, text)
                    for pericope in batch
                    if (text := _chunk_text(pericope, translation))
                ]
                if not keep:
                    continue
                parsed_batch = _parse_batch([text for _, text in keep])
                cur.executemany(
                    """
                    INSERT INTO pericope_annotations (
                        pericope_id, translation, pipeline, resolved_text, entities, svo
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (pericope_id, translation, pipeline) DO NOTHING
                    """,
                    [
                        (
                            pericope.id,
                            translation,
                            PIPELINE_VERSION,
                            parsed.resolved,
                            Jsonb([asdict(e) for e in parsed.entities]),
                            Jsonb([list(triple) for triple in parsed.svo]),
                        )
                        for (pericope, _), parsed in zip(keep, parsed_batch)
                    ],
                )
                conn.commit()
                annotated += len(keep)
    return annotated


def get_annotation(
    pericope_id: str,
    translation: str = "NIV",
    pipeline: str = PIPELINE_VERSION,
) -> dict | None:
    """Fetch one pericope's stored annotation row (resolved_text, entities,
    svo, extras) or None if it hasn't been processed."""
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT pericope_id, translation, pipeline, resolved_text, entities, svo, extras
                FROM pericope_annotations
                WHERE pericope_id = %s AND translation = %s AND pipeline = %s
                """,
                (pericope_id, translation, pipeline),
            )
            row = cur.fetchone()
    return row


def get_annotations(pericope_id: str, translation: str = "NIV") -> list[dict]:
    """Every pipeline's stored annotation for a pericope, ordered by
    pipeline name (so the local spaCy pipeline sorts ahead of the
    "together:..." LLM ones -- a stable order clients can rely on)."""
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT pericope_id, translation, pipeline, resolved_text, entities, svo, extras
                FROM pericope_annotations
                WHERE pericope_id = %s AND translation = %s
                ORDER BY pipeline
                """,
                (pericope_id, translation),
            )
            return cur.fetchall()
