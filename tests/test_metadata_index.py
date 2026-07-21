"""Tests for theo.metadata_index -- the denormalized STEP/theographic/NLP
search text theo.search's hybrid mode fuses in alongside chunk-text BM25.
_svo_text/_entity_text are pure and tested directly; the rest touches the
live dev DB, like the rest of this suite (see tests/conftest.py).
"""

from theo.metadata import Entity
from theo.metadata_index import _entity_text, _svo_text, build_search_text, index_pericopes
from theo.pericopes import list_pericopes
from theo.search import bm25_search, metadata_search


def test_svo_text_joins_triples():
    svo = [["Boaz", "marry", "Ruth"], ["Ruth", "bear", "Obed"]]
    assert _svo_text(svo) == "Boaz marry Ruth; Ruth bear Obed"


def test_svo_text_drops_placeholder_objects():
    # LLM triples use "none"/"nothing"/"" as the object of an intransitive
    # verb -- these shouldn't become a searchable "none" token.
    svo = [["the LORD", "keep silent", "none"], ["the Savior", "come", ""], ["the Savior", "come", "nothing"]]
    assert _svo_text(svo) == "the LORD keep silent; the Savior come; the Savior come"


def test_svo_text_empty_list_is_none():
    assert _svo_text([]) is None


def test_entity_text_includes_step_description():
    entity = Entity(name="Aaron", kind="person", source="step", description="High Priest", ustrong="H0175", data={})
    assert _entity_text(entity) == ["Aaron", "High Priest"]


def test_entity_text_excludes_theographic_description():
    # Theographic's `description` is the full Easton's Dictionary entry
    # (thousands of characters, identical across every pericope mentioning
    # the entity) -- indexing it would swamp the metadata index.
    entity = Entity(name="Aaron", kind="person", source="theographic", description="a very long dictionary entry" * 100, ustrong=None, data={})
    assert _entity_text(entity) == ["Aaron"]


def test_build_search_text_stays_bounded_for_a_well_known_figure():
    # Aaron's theographic dictionary_text alone is ~5,800 characters; if it
    # leaked into the index this pericope's search text would balloon.
    [pericope] = [p for p in list_pericopes("Exodus") if p.chapter_start == 4 and p.verse_start <= 14 <= p.verse_end]
    text = build_search_text(pericope)
    assert "Aaron" in text
    assert len(text) < 3000


def test_metadata_search_finds_step_only_vocabulary():
    # STEP describes Boaz as a "Kinsman-redeemer"; NIV's Ruth text always
    # says "guardian-redeemer" instead, so "kinsman" never appears in any
    # chunk's raw_text -- only theo.metadata_index's STEP-derived text has it.
    index_pericopes(book="Ruth")

    assert bm25_search("kinsman", limit=10) == []

    results = metadata_search("kinsman", limit=10)
    assert results
    assert any("Boaz" in r.pericope.title or "Ruth" in r.pericope.title for r in results)
