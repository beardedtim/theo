"""CLI: embed every pericope into the chunks_<dimensions> table matching
theo.embeddings' current model (BAAI/bge-large-en-v1.5, 1024-dim -> chunks_1024).

Usage:
    uv run embed_pericopes.py
"""

import tyro

from theo.chunks import embed_pericopes
from theo.embeddings import MODEL_NAME


def main(translation: str = "NIV", model: str = MODEL_NAME) -> None:
    """CLI: embed every pericope into the chunks_<dimensions> table matching
    theo.embeddings' current model (BAAI/bge-large-en-v1.5, 1024-dim -> chunks_1024).

    Args:
        translation: Translation to pull verse text from
        model: embedding_model label to store
    """
    submitted = embed_pericopes(translation=translation, model=model)
    print(f"Submitted {submitted} chunks for model {model!r} (duplicates skipped).")


if __name__ == "__main__":
    tyro.cli(main)
