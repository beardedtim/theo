def test_places_in_range(client):
    # Joshua 15:1-12 -- the boundary description of Judah's territory, dense
    # in named places.
    response = client.get("/places/6/15/1/15/12")

    assert response.status_code == 200
    places = response.json()
    assert "Adummim" in [p["kjv_name"] for p in places]
    assert {
        "id",
        "kjv_name",
        "display_title",
        "feature_type",
        "feature_sub_type",
        "latitude",
        "longitude",
        "dictionary_text",
    } <= places[0].keys()


def test_places_in_range_by_book_name(client):
    response = client.get("/places/Joshua/15/1/15/12")

    assert response.status_code == 200
    assert "Adummim" in [p["kjv_name"] for p in response.json()]


def test_places_in_range_bad_book(client):
    response = client.get("/places/NotABook/1/1/1/10")

    assert response.status_code == 404


def test_places_in_range_returns_list_even_when_sparse(client):
    response = client.get("/places/1/1/1/1/1")

    assert response.status_code == 200
    assert isinstance(response.json(), list)
