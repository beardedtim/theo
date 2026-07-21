"""CLI: derive benchmarks/search_golden_set.json (query -> relevant
pericope(s)) from Theographic event data. See theo/benchmark.py for the
derivation and filtering rationale.

Usage:
    uv run build_search_golden_set.py
"""

from pathlib import Path

import tyro

from theo.benchmark import (
    DEFAULT_GOLDEN_SET_PATH,
    MAX_CHAPTER_SPAN,
    MAX_RELEVANT_PERICOPES,
    build_golden_set,
    save_golden_set,
)


def main(
    output: Path = DEFAULT_GOLDEN_SET_PATH,
    max_chapter_span: int = MAX_CHAPTER_SPAN,
    max_relevant_pericopes: int = MAX_RELEVANT_PERICOPES,
) -> None:
    """CLI: derive a search-quality golden set from Theographic events and
    write it to `output`.

    Args:
        output: Path to write the golden set JSON to
        max_chapter_span: Widest (chapter_end - chapter_start) an event may span to be kept
        max_relevant_pericopes: Widest pericope-overlap count kept as a single-query gold set
    """
    queries = build_golden_set(max_chapter_span=max_chapter_span, max_relevant_pericopes=max_relevant_pericopes)
    save_golden_set(queries, output)

    single_target = sum(1 for q in queries if len(q.pericope_ids) == 1)
    print(f"Wrote {len(queries)} golden queries to {output} ({single_target} single-pericope, {len(queries) - single_target} multi-pericope).")


if __name__ == "__main__":
    tyro.cli(main)
