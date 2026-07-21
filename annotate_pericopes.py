"""CLI: run the spaCy/fastcoref NLP pipeline (theo.parse) over every
pericope and store entities, SVO triples, and coref-resolved text in the
`pericope_annotations` table.

Resumable: already-annotated pericopes are skipped, so rerunning after an
interruption picks up where it left off.

Usage:
    uv run annotate_pericopes.py                  # everything
    uv run annotate_pericopes.py --book Ruth      # one book
    uv run annotate_pericopes.py --limit 10       # smoke test
"""

import tyro

from theo.annotations import annotate_pericopes


def main(
    translation: str = "NIV",
    book: str | None = None,
    limit: int | None = None,
) -> None:
    """CLI: annotate pericopes with NLP metadata (NER entities with TIPNR
    uStrong ids, SVO triples, coref-resolved text).

    Args:
        translation: Translation to pull verse text from
        book: Optional book restriction, by number or name (e.g. "Ruth")
        limit: Optional cap on how many pericopes to process this run
    """
    annotated = annotate_pericopes(translation=translation, book=book, limit=limit)
    print(f"Annotated {annotated} pericopes (already-done ones skipped).")


if __name__ == "__main__":
    tyro.cli(main)
