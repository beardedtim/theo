"""Tests for the together.ai LLM enrichment flow (theo.llm_parse response
handling + theo.llm_annotations storage shapes). No live API calls -- the
parsing/shaping is exercised on canned responses, and the storage path is
exercised by writing a row under a throwaway pipeline key and reading it
back through theo.annotations and the /metadata endpoint.
"""

from types import SimpleNamespace

import pytest
from psycopg.types.json import Jsonb

from theo.annotations import get_annotation, get_annotations
from theo.db import get_connection
from theo.llm_annotations import _pack_verses
from theo.llm_parse import (
    DEFAULT_MODEL,
    LlmAnnotation,
    TogetherError,
    _extract_json,
    merge_parsed,
    pipeline_id,
    to_parsed,
)

_RESPONSE = {
    "resolved_text": "Boaz married Ruth, and Ruth bore Obed.",
    "entities": [
        {"text": "Boaz", "label": "PERSON"},
        {"text": "Ruth", "label": "PERSON"},
        {"text": "Obed", "label": "PERSON"},
    ],
    "svo": [
        {"subject": "Boaz", "verb": "marry", "object": "Ruth"},
        {"subject": "Ruth", "verb": "bear", "object": "Obed"},
    ],
    "themes": ["redemption", "lineage of David"],
    "keywords": ["kinsman-redeemer", "Obed"],
    "summary": "Boaz marries Ruth, who bears Obed, grandfather of David.",
    "tone": ["joyful"],
    "genre": "narrative",
    "speech_acts": [
        {"speaker": "the women", "addressee": "Naomi", "act": "blessing"},
    ],
}


def test_pipeline_id_includes_model():
    assert pipeline_id() == f"together:{DEFAULT_MODEL}/v1"
    assert pipeline_id("meta-llama/Llama-4-Maverick") == "together:meta-llama/Llama-4-Maverick/v1"


def test_extract_json_plain_and_fenced():
    import json

    plain = json.dumps(_RESPONSE)
    assert _extract_json(plain) == _RESPONSE
    fenced = f"```json\n{plain}\n```"
    assert _extract_json(fenced) == _RESPONSE
    with_think = f"<think>Ruth 4... entities...</think>\n{plain}"
    assert _extract_json(with_think) == _RESPONSE


def test_extract_json_rejects_non_json():
    with pytest.raises(TogetherError):
        _extract_json("Sorry, I can't annotate that passage.")


def test_to_parsed_matches_storage_shapes():
    parsed = to_parsed(LlmAnnotation.model_validate(_RESPONSE))

    # entities carry the exact keys spaCy rows store, offsets/ustrong None.
    assert parsed.entities[0] == {
        "text": "Boaz", "label": "PERSON", "start": None, "end": None, "ustrong": None,
    }
    assert ("Ruth", "bear", "Obed") in parsed.svo
    assert parsed.resolved.startswith("Boaz married")
    assert parsed.extras["genre"] == "narrative"
    assert parsed.extras["speech_acts"] == [
        {"speaker": "the women", "addressee": "Naomi", "act": "blessing"}
    ]
    assert set(parsed.extras) == {"summary", "genre", "themes", "keywords", "tone", "speech_acts"}


def test_llm_annotation_rejects_unknown_genre():
    with pytest.raises(Exception):
        LlmAnnotation.model_validate({**_RESPONSE, "genre": "sitcom"})


def test_pack_verses_boundaries():
    # Everything fits -> one segment, verses joined like _chunk_text does.
    assert _pack_verses(["a b", "c d", "e"], budget=100) == ["a b c d e"]
    # Budget forces splits, but only ever on verse boundaries.
    assert _pack_verses(["aaaa", "bbbb", "cccc"], budget=9) == ["aaaa bbbb", "cccc"]
    # A single verse longer than the budget becomes its own segment, intact.
    assert _pack_verses(["x" * 20, "yy"], budget=10) == ["x" * 20, "yy"]
    assert _pack_verses([]) == []


def test_merge_parsed_single_segment_stamps_count():
    parsed = to_parsed(LlmAnnotation.model_validate(_RESPONSE))
    merged = merge_parsed([parsed])

    assert merged.resolved == parsed.resolved
    assert merged.entities == parsed.entities
    assert merged.svo == parsed.svo
    assert merged.extras == {**parsed.extras, "segments": 1}


def test_merge_parsed_dedups_across_segments():
    part_one = to_parsed(LlmAnnotation.model_validate(_RESPONSE))
    part_two = to_parsed(LlmAnnotation.model_validate({
        **_RESPONSE,
        "resolved_text": "Obed became the father of Jesse.",
        "entities": [
            {"text": "Obed", "label": "PERSON"},   # duplicate of part one
            {"text": "Jesse", "label": "PERSON"},  # new
        ],
        "svo": [
            {"subject": "Ruth", "verb": "bear", "object": "Obed"},  # duplicate
            {"subject": "Obed", "verb": "father", "object": "Jesse"},
        ],
        "themes": ["lineage of David", "generations"],
        "summary": "Obed fathers Jesse.",
        "genre": "genealogy",
        "speech_acts": [],
    }))

    merged = merge_parsed([part_one, part_two])

    assert merged.resolved.endswith("father of Jesse.")
    entity_texts = [e["text"] for e in merged.entities]
    assert entity_texts == ["Boaz", "Ruth", "Obed", "Jesse"]  # deduped, order kept
    assert merged.svo.count(("Ruth", "bear", "Obed")) == 1
    assert ("Obed", "father", "Jesse") in merged.svo
    assert merged.extras["themes"] == ["redemption", "lineage of David", "generations"]
    assert merged.extras["summary"].count(".") == 2  # one sentence per segment
    assert merged.extras["genre"] == "narrative"  # tie -> first segment's genre wins
    assert merged.extras["segments"] == 2


def _patched_enrich_env(monkeypatch, parse_text_stub, verse_chars=1200):
    """Point _enrich's collaborators at stubs: a fixed verse list (fits one
    default-budget segment, splits under the halved budget) and a canned
    parse_text."""
    from theo import llm_annotations

    verses = [SimpleNamespace(text="w" * (verse_chars // 4)) for _ in range(4)]
    monkeypatch.setattr(llm_annotations, "get_verses_in_range", lambda *a: verses)
    monkeypatch.setattr(llm_annotations, "parse_text", parse_text_stub)
    return llm_annotations


def _pericope():
    from theo.pericopes import Pericope

    return Pericope(
        id="00000000-0000-0000-0000-000000000001", title="Test Pericope",
        book=8, chapter_start=1, verse_start=1, chapter_end=1, verse_end=4,
    )


def test_enrich_retries_truncated_responses(monkeypatch):
    """A truncated response gets a plain retry first, then a smaller-segment
    retry -- only persistent truncation fails the pericope."""
    from theo.llm_parse import TruncatedResponse

    parsed = to_parsed(LlmAnnotation.model_validate(_RESPONSE))
    calls: list[str] = []

    def flaky(reference, title, text, model=None):
        calls.append(reference)
        if len(calls) == 1:
            raise TruncatedResponse("truncated")
        return parsed

    llm_annotations = _patched_enrich_env(monkeypatch, flaky)

    merged = llm_annotations._enrich(_pericope(), "NIV", "test/model")

    assert merged is not None and merged.extras["segments"] == 1
    assert len(calls) == 2  # attempt 1 truncated, attempt 2 (same budget) ok


def test_enrich_halves_budget_on_second_truncation(monkeypatch):
    from theo.llm_parse import TruncatedResponse

    parsed = to_parsed(LlmAnnotation.model_validate(_RESPONSE))
    calls: list[tuple[str, int]] = []

    def flaky(reference, title, text, model=None):
        calls.append((reference, len(text)))
        if len(calls) <= 2:
            raise TruncatedResponse("truncated")
        return parsed

    llm_annotations = _patched_enrich_env(monkeypatch, flaky, verse_chars=8000)
    monkeypatch.setattr(llm_annotations, "_BUDGET_ATTEMPTS", (6000, 6000, 3000))

    merged = llm_annotations._enrich(_pericope(), "NIV", "test/model")

    # Attempts 1+2 at budget 6000 -> two segments each; the first segment of
    # each truncates. Attempt 3 at budget 3000 -> one segment per 2000-char
    # verse, all ok.
    assert merged is not None and merged.extras["segments"] == 4
    assert "(part 1 of 2)" in calls[0][0] and "(part 1 of 2)" in calls[1][0]
    assert all("of 4)" in ref for ref, _ in calls[2:])


def test_enrich_raises_after_final_truncation(monkeypatch):
    from theo.llm_parse import TruncatedResponse

    def always_truncated(reference, title, text, model=None):
        raise TruncatedResponse("truncated")

    llm_annotations = _patched_enrich_env(monkeypatch, always_truncated)

    with pytest.raises(TruncatedResponse):
        llm_annotations._enrich(_pericope(), "NIV", "test/model")


def test_retry_after_seconds_parses_header():
    from theo.llm_parse import _retry_after_seconds

    assert _retry_after_seconds(SimpleNamespace(headers={"x-ratelimit-reset": "2"})) == 2.0
    assert _retry_after_seconds(SimpleNamespace(headers={})) is None
    assert _retry_after_seconds(SimpleNamespace(headers={"x-ratelimit-reset": "soon"})) is None


def test_rate_limiter_spaces_calls(monkeypatch):
    """N calls in a row are scheduled `interval` apart on a shared clock, not
    "interval after my own last call" -- the pacing this exists for is
    against a burst of concurrent worker threads, not a single caller."""
    from theo.llm_parse import _RateLimiter

    clock = [0.0]
    sleeps: list[float] = []
    monkeypatch.setattr("theo.llm_parse.time.monotonic", lambda: clock[0])

    def fake_sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr("theo.llm_parse.time.sleep", fake_sleep)

    limiter = _RateLimiter(0.5)
    limiter.wait()  # clock is already at slot 0 -> no delay
    limiter.wait()
    limiter.wait()

    assert sleeps == [0.5, 0.5]


def test_post_completion_honors_ratelimit_reset_header(monkeypatch):
    """A 429 with x-ratelimit-reset sleeps exactly that long, not the
    2**attempt guess -- together.ai's dynamic limiter reports the real wait."""
    from theo import llm_parse

    monkeypatch.setenv("TOGETHER_API_KEY", "test-key")
    monkeypatch.setattr(llm_parse, "_rate_limiter", llm_parse._RateLimiter(0.0))
    responses = iter([
        SimpleNamespace(status_code=429, headers={"x-ratelimit-reset": "2.5"}, text="rate limited"),
        SimpleNamespace(status_code=200, headers={}, json=lambda: {"ok": True}),
    ])
    monkeypatch.setattr(llm_parse.httpx, "post", lambda *a, **k: next(responses))
    sleeps: list[float] = []
    monkeypatch.setattr(llm_parse.time, "sleep", lambda s: sleeps.append(s))

    assert llm_parse._post_completion({}, timeout=5.0) == {"ok": True}
    assert sleeps == [2.5]


def test_post_completion_falls_back_to_exponential_backoff(monkeypatch):
    """No rate-limit header (e.g. a plain 500) -> the 2**attempt guess."""
    from theo import llm_parse

    monkeypatch.setenv("TOGETHER_API_KEY", "test-key")
    monkeypatch.setattr(llm_parse, "_rate_limiter", llm_parse._RateLimiter(0.0))
    responses = iter([
        SimpleNamespace(status_code=500, headers={}, text="boom"),
        SimpleNamespace(status_code=200, headers={}, json=lambda: {"ok": True}),
    ])
    monkeypatch.setattr(llm_parse.httpx, "post", lambda *a, **k: next(responses))
    sleeps: list[float] = []
    monkeypatch.setattr(llm_parse.time, "sleep", lambda s: sleeps.append(s))

    assert llm_parse._post_completion({}, timeout=5.0) == {"ok": True}
    assert sleeps == [2]


def test_set_min_request_interval_updates_shared_limiter(monkeypatch):
    from theo import llm_parse

    fresh = llm_parse._RateLimiter(0.5)
    monkeypatch.setattr(llm_parse, "_rate_limiter", fresh)

    llm_parse.set_min_request_interval(1.25)

    assert fresh._interval == 1.25


def test_missing_api_key_fails_fast(monkeypatch):
    """A missing key must abort before anything is dispatched -- not surface
    as thousands of identical per-pericope failures."""
    from theo.llm_annotations import llm_annotate_pericopes

    monkeypatch.delenv("TOGETHER_API_KEY", raising=False)
    with pytest.raises(TogetherError):
        llm_annotate_pericopes(book="Ruth", limit=1, model="test/never-run")


@pytest.fixture()
def stored_llm_annotation(client):
    """A storage-shaped LLM row for the first Ruth pericope under a
    throwaway pipeline key, removed again afterwards."""
    pericope = client.get("/pericopes/Ruth").json()[0]
    pipeline = "together:test-model/v0"
    parsed = to_parsed(LlmAnnotation.model_validate(_RESPONSE))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO pericope_annotations (
                    pericope_id, translation, pipeline, resolved_text, entities, svo, extras
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    pericope["id"], "NIV", pipeline, parsed.resolved,
                    Jsonb(parsed.entities),
                    Jsonb([list(t) for t in parsed.svo]),
                    Jsonb(parsed.extras),
                ),
            )
        conn.commit()
    yield pericope, pipeline
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM pericope_annotations WHERE pipeline = %s", (pipeline,)
            )
        conn.commit()


def test_llm_row_roundtrips_through_readers(stored_llm_annotation):
    pericope, pipeline = stored_llm_annotation

    row = get_annotation(pericope["id"], "NIV", pipeline)
    assert row is not None
    assert row["extras"]["themes"] == ["redemption", "lineage of David"]

    # get_annotations returns every pipeline's row, spaCy's ("en...") first.
    rows = get_annotations(pericope["id"], "NIV")
    assert pipeline in {r["pipeline"] for r in rows}
    pipelines = [r["pipeline"] for r in rows]
    assert pipelines == sorted(pipelines)


def test_metadata_prefers_llm_annotation(client, stored_llm_annotation):
    """/metadata returns ONE annotation per pericope, LLM pipelines
    outranking spaCy (see theo.metadata.ANNOTATION_PIPELINES). The fixture
    row wins even over real together:* rows -- same priority prefix, and
    "test-model..." sorts above "deepseek-ai..." on the version tiebreak."""
    pericope, pipeline = stored_llm_annotation

    metadata = client.get(f"/metadata/pericope/{pericope['id']}").json()

    rows = [a for a in metadata["annotations"] if a["pericope_id"] == pericope["id"]]
    assert len(rows) == 1
    llm = rows[0]
    assert llm["pipeline"] == pipeline
    assert llm["extras"]["summary"].startswith("Boaz marries Ruth")
    assert ["Ruth", "bear", "Obed"] in llm["svo"]
