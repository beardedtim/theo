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
