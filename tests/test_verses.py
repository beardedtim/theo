def test_get_chapter_by_book_number(client):
    response = client.get("/verses/1/1")

    assert response.status_code == 200
    verses = response.json()
    assert len(verses) == 31  # NIV Genesis 1
    assert [v["verse"] for v in verses] == list(range(1, 32))
    assert all(v["book"] == "Genesis" and v["chapter"] == 1 for v in verses)


def test_get_chapter_by_book_name(client):
    by_name = client.get("/verses/Genesis/1").json()
    by_number = client.get("/verses/1/1").json()

    assert by_name == by_number


def test_get_chapter_not_found(client):
    response = client.get("/verses/1/9999")

    assert response.status_code == 404


def test_get_chapter_bad_book_name(client):
    response = client.get("/verses/NotABook/1")

    assert response.status_code == 404


def test_get_verse_range(client):
    response = client.get("/verses/1/1/1/3")

    assert response.status_code == 200
    verses = response.json()
    assert [v["verse"] for v in verses] == [1, 2, 3]


def test_get_verse_range_not_found(client):
    response = client.get("/verses/1/9999/1/3")

    assert response.status_code == 404
