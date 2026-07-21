"""Parser and reader tests for the STEPBible brief lexicons (theo.lexicon).
No API endpoints yet -- these will back the future combined metadata route --
so unlike the other test modules this exercises the module directly: the
parser against the real TBESH/TBESG files, the readers against the ingested
`step_lexicon` table.
"""

import unicodedata

from theo.lexicon import (
    TBESG_PATH,
    TBESH_PATH,
    get_lexicon_entries,
    parse_lexicon,
    search_lexicon,
)


def test_parse_hebrew_lexicon():
    entries = parse_lexicon(TBESH_PATH, "hebrew")

    assert len(entries) == 11682
    by_dstrong = {e.dstrong: e for e in entries}
    aaron = by_dstrong["H0175"]
    assert aaron.gloss == "Aaron"
    assert aaron.original == "אַהֲרֹן"
    assert aaron.morph == "N:N-M-P"
    # Aramaic entries point at their Hebrew equivalent.
    av = by_dstrong["H0002"]
    assert av.relation == "in Aramaic of"
    assert av.ustrong == "H0001G"


def test_parse_greek_lexicon():
    entries = parse_lexicon(TBESG_PATH, "greek")

    assert len(entries) == 11035
    by_dstrong = {e.dstrong: e for e in entries}
    agape = by_dstrong["G0026"]
    assert agape.gloss == "love"
    # The source uses combining accents (NFD-ish), so compare normalized.
    assert unicodedata.normalize("NFC", agape.original) == "ἀγάπη"
    # Greek forms of Hebrew names unify under the Hebrew uStrong.
    greek_aaron = by_dstrong["G0002"]
    assert greek_aaron.relation == "the Greek of"
    assert greek_aaron.ustrong == "H0175"


def test_parse_compound_ustrong_keeps_raw():
    entries = parse_lexicon(TBESH_PATH, "hebrew")
    compounds = [e for e in entries if e.ustrong_raw]

    assert compounds  # e.g. "H9007 (H9007+H9005)"
    assert all(e.ustrong_raw.split()[0].rstrip(",") == e.ustrong for e in compounds)


def test_get_lexicon_entries_unifies_testaments():
    # Aaron's uStrong (H0175, same id as TIPNR's step_names row) fans out
    # to both the Hebrew entry and its Greek form.
    entries = get_lexicon_entries("H0175")

    assert {e.dstrong for e in entries} >= {"H0175", "G0002"}
    assert {e.language for e in entries} == {"hebrew", "greek"}


def test_get_lexicon_entries_unknown_code():
    assert get_lexicon_entries("H9999X") == []


def test_search_lexicon():
    entries = search_lexicon("steadfast love", limit=20)

    # agape's meaning discusses love at length; it should rank.
    assert "G0026" in {e.dstrong for e in entries}
    assert all(e.language in ("hebrew", "greek") for e in entries)


def test_lexicon_search_endpoint(client):
    response = client.get("/lexicon", params={"q": "love"})

    assert response.status_code == 200
    entries = response.json()
    assert "G0026" in {e["dstrong"] for e in entries}
    assert {"dstrong", "estrong", "ustrong", "relation", "language",
            "original", "transliteration", "morph", "gloss", "meaning_html"} <= entries[0].keys()


def test_lexicon_lookup_endpoint_fans_out_by_ustrong(client):
    # Aaron's uStrong returns both the Hebrew entry and its Greek form.
    response = client.get("/lexicon/H0175")

    assert response.status_code == 200
    entries = response.json()
    assert {e["dstrong"] for e in entries} >= {"H0175", "G0002"}
    assert {e["language"] for e in entries} == {"hebrew", "greek"}


def test_lexicon_lookup_endpoint_by_dstrong(client):
    response = client.get("/lexicon/G2264H")

    assert response.status_code == 200
    assert any(e["gloss"] == "Herod" for e in response.json())


def test_lexicon_lookup_endpoint_unknown_code(client):
    response = client.get("/lexicon/H9999X")

    assert response.status_code == 404


def test_lexicon_search_endpoint_survives_query_syntax_characters(client):
    response = client.get("/lexicon", params={"q": 'steadfast "love'})

    assert response.status_code == 200
