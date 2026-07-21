"""CLI: run the together.ai LLM enrichment (theo.llm_parse) over every
pericope and store entities, SVO triples, coref-resolved text, and the
extras bundle (summary, genre, themes, keywords, tone, speech acts) in the
`pericope_annotations` table, under a "together:<model>/v1" pipeline key
alongside the local spaCy pipeline's rows.

Requires TOGETHER_API_KEY in .env. Resumable: already-annotated pericopes
are skipped and failures are just logged, so rerunning after an
interruption (or to retry failures) picks up where it left off.

Usage:
    uv run llm_annotate_pericopes.py                  # everything
    uv run llm_annotate_pericopes.py --book Ruth      # one book
    uv run llm_annotate_pericopes.py --limit 5        # smoke test
"""

import logging

import tyro

from theo.llm_annotations import llm_annotate_pericopes
from theo.llm_parse import DEFAULT_MODEL


def main(
    translation: str = "NIV",
    book: str | None = None,
    limit: int | None = None,
    model: str = DEFAULT_MODEL,
    concurrency: int = 8,
    min_request_interval: float = 0.5,
) -> None:
    """CLI: enrich pericopes with LLM-derived NLP metadata via together.ai.

    Args:
        translation: Translation to pull verse text from
        book: Optional book restriction, by number or name (e.g. "Ruth")
        limit: Optional cap on how many pericopes to process this run
        model: together.ai model id; also part of the stored pipeline key
        concurrency: Number of API requests in flight at once
        min_request_interval: Minimum seconds between request dispatches,
            shared across all `concurrency` workers. Raise this if a run is
            hitting 429s.
    """
    # httpx logs every request at INFO; thousands of "HTTP Request: POST ..."
    # lines would drown the progress bar and any real failure.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    annotated, failed = llm_annotate_pericopes(
        translation=translation, book=book, limit=limit, model=model,
        concurrency=concurrency, min_request_interval=min_request_interval,
    )
    print(f"Annotated {annotated} pericopes, {failed} failed (already-done ones skipped).")


if __name__ == "__main__":
    tyro.cli(main)
