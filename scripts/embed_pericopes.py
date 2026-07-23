"""CLI: embed every pericope into the chunks_<dimensions> table matching
theo.embeddings' current model (BAAI/bge-large-en-v1.5, 1024-dim -> chunks_1024).

Usage:
    uv run -m scripts.embed_pericopes
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
    written = embed_pericopes(translation=translation, model=model)
    print(f"Wrote {written} chunks for model {model!r} (already-current pericopes skipped).")


if __name__ == "__main__":
    tyro.cli(main)
