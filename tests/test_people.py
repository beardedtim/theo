def test_people_in_range(client):
    # 1 Chronicles 1:1-27 -- a genealogy verse-dense in named people.
    response = client.get("/people/13/1/1/1/27")

    assert response.status_code == 200
    people = response.json()
    assert "Abraham" in [p["name"] for p in people]
    assert {"id", "name", "display_title", "gender", "also_called", "birth_year", "death_year", "dictionary_text"} <= (
        people[0].keys()
    )


def test_people_in_range_by_book_name(client):
    # Genesis 5 -- the genealogy from Adam to Noah.
    response = client.get("/people/Genesis/5/1/5/32")

    assert response.status_code == 200
    assert "Noah" in [p["name"] for p in response.json()]


def test_people_in_range_bad_book(client):
    response = client.get("/people/NotABook/1/1/1/10")

    assert response.status_code == 404


def test_people_in_range_returns_list_even_when_sparse(client):
    response = client.get("/people/1/1/1/1/1")

    assert response.status_code == 200
    assert isinstance(response.json(), list)
