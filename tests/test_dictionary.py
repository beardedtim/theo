def test_search_dictionary(client):
    response = client.get("/dictionary", params={"q": "phylactery"})

    assert response.status_code == 200
    entries = response.json()
    assert entries[0]["term"] == "Phylacteries"


def test_search_dictionary_limit(client):
    response = client.get("/dictionary", params={"q": "Jerusalem", "limit": 3})

    assert response.status_code == 200
    assert len(response.json()) <= 3


def test_search_dictionary_requires_query(client):
    response = client.get("/dictionary")

    assert response.status_code == 422


def test_get_dictionary_entry(client):
    entry_id = client.get("/dictionary", params={"q": "phylactery"}).json()[0]["id"]

    response = client.get(f"/dictionary/{entry_id}")

    assert response.status_code == 200
    assert response.json()["term"] == "Phylacteries"


def test_get_dictionary_entry_not_found(client):
    response = client.get("/dictionary/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
