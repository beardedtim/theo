"""Tests for the combined /metadata endpoints -- the single call that
bundles pericopes, a source-prioritized entities list, events, lexicon
entries, and one NLP annotation per pericope.
"""

_KEYS = {
    "book", "chapter_start", "verse_start", "chapter_end", "verse_end",
    "pericopes", "entities", "events", "lexicon", "annotations",
}


def test_metadata_by_range(client):
    # Exodus 4:14 -- Aaron, Levi, and Moses in one verse.
    response = client.get("/metadata/Exodus/4/14/4/14", params={"translation": "NIV"})

    assert response.status_code == 200
    metadata = response.json()
    assert _KEYS <= metadata.keys()
    assert metadata["book"] == 2

    names = {e["name"] for e in metadata["entities"]}
    assert {"Aaron", "Levi", "Moses"} <= names
    aaron = next(e for e in metadata["entities"] if e["name"] == "Aaron")
    assert aaron["kind"] == "person"
    assert aaron["source"] == "step"  # STEP outranks theographic
    assert aaron["data"]["ustrong"] == aaron["ustrong"]
    # Every STEP entity's ustrong resolves to lexicon entries (H0175 = Aaron).
    assert "H0175" in metadata["lexicon"]
    assert any(e["gloss"] == "Aaron" for e in metadata["lexicon"]["H0175"])
    # The verse sits inside a pericope, whose NLP annotation comes along.
    assert metadata["pericopes"]
    assert metadata["annotations"]
    annotation = metadata["annotations"][0]
    assert annotation["pericope_id"] in {p["id"] for p in metadata["pericopes"]}
    assert annotation["entities"] and annotation["svo"]


def test_metadata_entities_are_deduplicated(client):
    metadata = client.get("/metadata/Ruth/1/1/1/22").json()

    keys = [(e["kind"], e["name"].casefold()) for e in metadata["entities"]]
    assert len(keys) == len(set(keys))


def test_metadata_prefers_step_and_falls_back_to_theographic(client):
    metadata = client.get("/metadata/Ruth/1/1/1/22").json()
    step_names = client.get("/names/Ruth/1/1/1/22").json()

    # Every STEP proper noun in the range surfaces as a step-sourced entity.
    step_entities = [e for e in metadata["entities"] if e["source"] == "step"]
    assert {e["data"]["id"] for e in step_entities} == {n["id"] for n in step_names}
    # A theographic entity only appears when STEP doesn't already name it.
    step_keys = {(e["kind"], e["name"].casefold()) for e in step_entities}
    for entity in metadata["entities"]:
        if entity["source"] == "theographic":
            assert (entity["kind"], entity["name"].casefold()) not in step_keys
            assert entity["ustrong"] is None


def test_metadata_one_annotation_per_pericope(client):
    metadata = client.get("/metadata/Ruth/1/1/1/22").json()

    pericope_ids = [a["pericope_id"] for a in metadata["annotations"]]
    assert len(pericope_ids) == len(set(pericope_ids))


def test_metadata_by_range_bad_book(client):
    response = client.get("/metadata/NotABook/1/1/1/10")

    assert response.status_code == 404


def test_metadata_by_pericope(client):
    pericope = client.get("/pericopes/Ruth").json()[0]

    response = client.get(f"/metadata/pericope/{pericope['id']}")

    assert response.status_code == 200
    metadata = response.json()
    assert _KEYS <= metadata.keys()
    assert pericope["id"] in {p["id"] for p in metadata["pericopes"]}
    assert metadata["book"] == 8
    assert metadata["chapter_start"] == pericope["chapter_start"]
    assert metadata["verse_end"] == pericope["verse_end"]
    # Ruth 1: Naomi and her family, with their lexicon entries linked.
    naomi = next(e for e in metadata["entities"] if e["name"] == "Naomi")
    assert naomi["ustrong"] in metadata["lexicon"]
    # Its own annotation is present.
    assert pericope["id"] in {a["pericope_id"] for a in metadata["annotations"]}


def test_metadata_by_pericope_not_found(client):
    response = client.get("/metadata/pericope/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
