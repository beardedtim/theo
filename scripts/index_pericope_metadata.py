"""CLI: (re)build `pericope_metadata_index`, the denormalized STEP +
theographic + NLP-annotation search text theo.search's hybrid mode fuses in
alongside chunk-text BM25 and semantic similarity.

Run after ingest_step_names.py, ingest_people/places/people_groups.py, and
annotate_pericopes.py / llm_annotate_pericopes.py -- it reads their output.
Safe to rerun any time any of those change: it upserts by
(pericope_id, translation).

Usage:
    uv run -m scripts.index_pericope_metadata                  # everything
    uv run -m scripts.index_pericope_metadata --book Ruth      # one book
"""

import tyro

from theo.metadata_index import index_pericopes


def main(translation: str = "NIV", book: str | None = None) -> None:
    """CLI: rebuild the metadata search index.

    Args:
        translation: Translation whose NLP annotations to pull SVO/entities from
        book: Optional book restriction, by number or name (e.g. "Ruth")
    """
    written = index_pericopes(translation=translation, book=book)
    print(f"Indexed metadata for {written} pericopes.")


if __name__ == "__main__":
    tyro.cli(main)
