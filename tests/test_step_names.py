def test_names_in_range(client):
    # Exodus 4:14 -- "Is not Aaron the Levite your brother?" TIPNR tags
    # Aaron, Levi, and Moses in this one verse.
    response = client.get("/names/2/4/14/4/14")

    assert response.status_code == 200
    names = response.json()
    assert sorted(n["name"] for n in names) == ["Aaron", "Levi", "Moses"]
    assert {"id", "name", "category", "entity_type", "description", "brief"} <= names[0].keys()


def test_names_in_range_by_book_name(client):
    response = client.get("/names/Exodus/4/14/4/14")

    assert response.status_code == 200
    assert "Aaron" in [n["name"] for n in response.json()]


def test_names_in_range_bad_book(client):
    response = client.get("/names/NotABook/1/1/1/10")

    assert response.status_code == 404


def test_names_in_range_returns_list_even_when_sparse(client):
    # Psalm 117 (the shortest chapter) names no individuals.
    response = client.get("/names/19/117/1/117/2")

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_names_search(client):
    response = client.get("/names", params={"q": "first high priest of Israel"})

    assert response.status_code == 200
    assert "Aaron" in [n["name"] for n in response.json()]


def test_name_detail(client):
    aaron = next(
        n for n in client.get("/names/2/4/14/4/14").json() if n["name"] == "Aaron"
    )
    response = client.get(f"/name/{aaron['id']}")

    assert response.status_code == 200
    detail = response.json()
    assert detail["ustrong"] == "H0175"
    assert detail["category"] == "person"
    assert detail["entity_type"] == "Male"
    assert detail["tribe"] == "Tribe of Levi"
    assert detail["article_html"]
    # Aaron has a Hebrew ("Named") and a Greek form.
    assert {f["significance"] for f in detail["forms"]} == {"Named", "Greek"}
    # His refs span from Exodus into the New Testament (Hebrews).
    books = {r["book"] for r in detail["refs"]}
    assert 2 in books and 58 in books


def test_name_detail_place_has_coordinates(client):
    abana = next(
        n for n in client.get("/names", params={"q": "Abana"}).json() if n["name"] == "Abana"
    )
    detail = client.get(f"/name/{abana['id']}").json()

    assert detail["category"] == "place"
    assert abs(detail["latitude"] - 33.545097) < 1e-6
    assert abs(detail["longitude"] - 36.224661) < 1e-6


def test_name_detail_not_found(client):
    response = client.get("/name/not-a-uuid")

    assert response.status_code == 404
