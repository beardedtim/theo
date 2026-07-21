def test_search_bm25(client):
    response = client.get("/search", params={"q": "a shepherd caring for lost sheep", "mode": "bm25", "limit": 3})

    assert response.status_code == 200
    results = response.json()
    assert len(results) <= 3
    assert {"pericope", "verses", "score"} <= results[0].keys()


def test_search_hybrid_default_mode(client):
    response = client.get("/search", params={"q": "a shepherd caring for lost sheep", "limit": 3})

    assert response.status_code == 200
    assert len(response.json()) <= 3


def test_search_semantic(client):
    response = client.get("/search", params={"q": "a shepherd caring for lost sheep", "mode": "semantic", "limit": 3})

    assert response.status_code == 200
    assert len(response.json()) <= 3


def test_search_requires_query(client):
    response = client.get("/search")

    assert response.status_code == 422


def test_search_rejects_unknown_mode(client):
    response = client.get("/search", params={"q": "test", "mode": "bogus"})

    assert response.status_code == 422


def test_search_bm25_survives_query_syntax_characters(client):
    # Regression test: raw_text @@@ 'shepherd''s heart' is a tantivy parse
    # error (unbalanced quote) that used to surface as a 500.
    response = client.get("/search", params={"q": "shepherd's heart", "mode": "bm25"})

    assert response.status_code == 200


def test_search_hybrid_survives_query_syntax_characters(client):
    response = client.get("/search", params={"q": "shepherd's heart", "mode": "hybrid"})

    assert response.status_code == 200


def test_search_bm25_query_sanitizing_to_empty_returns_empty_list(client):
    # "()" sanitizes to the empty string; @@@ '' is itself a parse error,
    # so this must short-circuit rather than query the database.
    response = client.get("/search", params={"q": "()", "mode": "bm25"})

    assert response.status_code == 200
    assert response.json() == []


def test_search_hybrid_surfaces_metadata_only_matches(client):
    # STEP describes Boaz as a "Kinsman-redeemer"; NIV's Ruth text always
    # says "guardian-redeemer" instead, so the word "kinsman" never occurs
    # in any chunk's raw_text -- only theo.metadata_index's STEP-derived
    # text has it. hybrid mode should still surface Ruth/Boaz for it even
    # though bm25 mode (chunk text only) can't.
    bm25_response = client.get("/search", params={"q": "kinsman", "mode": "bm25", "limit": 10})
    assert bm25_response.json() == []

    hybrid_response = client.get("/search", params={"q": "kinsman", "mode": "hybrid", "limit": 10})
    assert hybrid_response.status_code == 200
    titles = [r["pericope"]["title"] for r in hybrid_response.json()]
    assert any("Boaz" in t or "Ruth" in t for t in titles)
