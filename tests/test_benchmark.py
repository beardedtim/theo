import pytest

from theo.benchmark import (
    MAX_CHAPTER_SPAN,
    MAX_RELEVANT_PERICOPES,
    GoldQuery,
    _recall_at_k,
    _reciprocal_rank,
    build_golden_set,
    evaluate_mode,
    load_golden_set,
    misses,
    save_golden_set,
)
from theo.pericopes import Pericope
from theo.search import SearchResult


def test_recall_at_k_counts_fraction_of_relevant_found():
    assert _recall_at_k(["a", "b", "c"], {"a", "z"}, k=3) == 0.5  # 1 of 2 relevant found
    assert _recall_at_k(["a", "b"], {"a", "b"}, k=1) == 0.5  # only "a" within top 1
    assert _recall_at_k(["x", "y"], {"a"}, k=10) == 0.0
    assert _recall_at_k(["a"], set(), k=10) == 0.0  # no relevant docs -> defined as 0, not div-by-zero


def test_reciprocal_rank_first_hit_and_no_hit():
    assert _reciprocal_rank(["x", "a", "b"], {"a", "b"}) == pytest.approx(0.5)  # first hit at rank 2
    assert _reciprocal_rank(["x", "y"], {"a"}) == 0.0


def _gold(event_id, query, pericope_ids, pericope_titles):
    return GoldQuery(
        event_id=event_id, query=query, reference=f"Test {event_id}",
        book=1, chapter_start=1, verse_start=1, chapter_end=1, verse_end=1,
        pericope_ids=pericope_ids, pericope_titles=pericope_titles,
    )


def _result(pericope_id, title, score=1.0):
    pericope = Pericope(id=pericope_id, title=title, book=1, chapter_start=1, verse_start=1, chapter_end=1, verse_end=1)
    return SearchResult(pericope=pericope, verses=[], score=score)


def test_evaluate_mode_scores_hit_and_miss_queries(monkeypatch):
    gold_hit = _gold("e1", "q1", ["p1"], ["Pericope One"])
    gold_miss = _gold("e2", "q2", ["p2"], ["Pericope Two"])

    canned = {
        "q1": [_result("other", "Other"), _result("p1", "Pericope One")],  # hit at rank 2
        "q2": [_result("other", "Other")],  # never appears
    }

    def fake_search(query, mode="hybrid", translation="NIV", limit=10, **kwargs):
        return canned[query]

    monkeypatch.setattr("theo.benchmark.run_search", fake_search)

    report = evaluate_mode([gold_hit, gold_miss], mode="hybrid", k_values=(1, 5))

    assert report.n == 2
    assert report.recall_at[1] == pytest.approx(0.0)  # q1's hit is rank 2, so top-1 misses too; q2 never hits
    assert report.recall_at[5] == pytest.approx(0.5)  # q1 found within top 5 (1.0), q2 not (0.0) -> mean 0.5
    assert report.mrr == pytest.approx(0.25)  # (0.5 + 0.0) / 2

    total_misses = misses(report, k=5)
    assert [o.query.event_id for o in total_misses] == ["e2"]


def test_build_golden_set_invariants():
    """Exercises the real derivation against the live dev DB (see
    tests/conftest.py -- this suite assumes one is up and ingested)."""
    queries = build_golden_set()

    assert len(queries) > 100
    by_query = {q.query: q for q in queries}

    # Spot-check a couple of well-known, unambiguous single-pericope events.
    assert by_query["The Fall"].pericope_titles == ["The Fall"]
    assert by_query["Creation of Adam and Eve"].pericope_titles == ["Adam and Eve"]

    for q in queries:
        assert q.chapter_end - q.chapter_start <= MAX_CHAPTER_SPAN
        assert 1 <= len(q.pericope_ids) <= MAX_RELEVANT_PERICOPES
        assert len(q.pericope_ids) == len(q.pericope_titles)


def test_golden_set_roundtrips_through_json(tmp_path):
    queries = [_gold("e1", "q1", ["p1"], ["Pericope One"])]
    path = tmp_path / "golden.json"

    save_golden_set(queries, path)
    loaded = load_golden_set(path)

    assert loaded == queries
