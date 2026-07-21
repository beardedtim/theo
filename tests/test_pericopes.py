def test_list_pericopes(client):
    response = client.get("/pericopes")

    assert response.status_code == 200
    pericopes = response.json()
    assert len(pericopes) > 0
    assert {"id", "title", "book", "chapter_start", "verse_start", "chapter_end", "verse_end"} <= pericopes[0].keys()


def test_list_pericopes_filtered_by_book(client):
    response = client.get("/pericopes", params={"book": "1"})

    assert response.status_code == 200
    pericopes = response.json()
    assert len(pericopes) > 0
    assert all(p["book"] == 1 for p in pericopes)


def test_list_pericopes_search(client):
    response = client.get("/pericopes", params={"q": "shepherd"})

    assert response.status_code == 200
    titles = [p["title"] for p in response.json()]
    assert "The Good Shepherd and His Sheep" in titles


def test_list_pericopes_search_survives_query_syntax_characters(client):
    response = client.get("/pericopes", params={"q": "prodigal's"})

    assert response.status_code == 200


def test_pericopes_for_book(client):
    response = client.get("/pericopes/1")

    assert response.status_code == 200
    pericopes = response.json()
    assert len(pericopes) > 0
    assert all(p["book"] == 1 for p in pericopes)


def test_pericopes_for_book_not_found(client):
    response = client.get("/pericopes/9999")

    assert response.status_code == 404


def test_get_pericope_detail(client):
    pericope_id = client.get("/pericopes/1").json()[0]["id"]

    response = client.get(f"/pericope/{pericope_id}")

    assert response.status_code == 200
    detail = response.json()
    assert detail["pericope"]["id"] == pericope_id
    assert len(detail["verses"]) > 0


def test_get_pericope_not_found(client):
    response = client.get("/pericope/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
