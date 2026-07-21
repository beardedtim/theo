def test_list_events_chronological(client):
    response = client.get("/events")

    assert response.status_code == 200
    events = response.json()
    assert len(events) > 0
    sort_keys = [e["sort_key"] for e in events]
    assert sort_keys == sorted(sort_keys)
    assert events[0]["title"] == "Creation of all things"


def test_events_in_range(client):
    response = client.get("/events/1/1/1/2/25")

    assert response.status_code == 200
    titles = [e["title"] for e in response.json()]
    assert "Creation of all things" in titles
    assert "Creation of Adam and Eve" in titles


def test_events_in_range_bad_book(client):
    response = client.get("/events/NotABook/1/1/1/10")

    assert response.status_code == 404


def test_get_event_detail(client):
    event_id = client.get("/events/1/1/1/2/25").json()[0]["id"]

    response = client.get(f"/event/{event_id}")

    assert response.status_code == 200
    detail = response.json()
    assert detail["event"]["id"] == event_id
    assert "God" in [p["name"] for p in detail["participants"]]


def test_get_event_not_found(client):
    response = client.get("/event/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
