"""Unit tests for the verse-boundary chunk packing in theo.chunks."""

from theo.chunks import TOKEN_BUDGET, pack_segments
from theo.embeddings import MAX_TOKENS


def test_budget_leaves_headroom_under_model_limit():
    assert TOKEN_BUDGET < MAX_TOKENS


def test_everything_fits_in_one_segment():
    assert pack_segments(["a", "b", "c"], [100, 100, 100], budget=480) == ["a b c"]


def test_splits_on_verse_boundary_when_over_budget():
    texts = ["v1", "v2", "v3", "v4"]
    assert pack_segments(texts, [200, 200, 200, 200], budget=480) == ["v1 v2", "v3 v4"]


def test_exact_budget_fill_does_not_split():
    assert pack_segments(["a", "b"], [240, 240], budget=480) == ["a b"]


def test_oversized_single_verse_becomes_own_segment():
    assert pack_segments(["big", "small"], [600, 10], budget=480) == ["big", "small"]


def test_empty_input():
    assert pack_segments([], []) == []
