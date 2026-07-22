"""Tests for /passage-groups -- the canon-structure taxonomy (Pentateuch,
Old/New Testament, ...), synced from passage_groups.yaml.
"""


def test_list_passage_groups(client):
    response = client.get("/passage-groups")

    assert response.status_code == 200
    slugs = {g["slug"] for g in response.json()}
    assert {"pentateuch", "old-testament", "new-testament", "gospels"} <= slugs


def test_get_passage_group_detail(client):
    response = client.get("/passage-groups/pentateuch")

    assert response.status_code == 200
    detail = response.json()
    assert detail["group"]["slug"] == "pentateuch"
    assert detail["books"] == [1, 2, 3, 4, 5]


def test_get_passage_group_detail_children(client):
    response = client.get("/passage-groups/old-testament")

    assert response.status_code == 200
    detail = response.json()
    child_slugs = {c["slug"] for c in detail["children"]}
    assert "pentateuch" in child_slugs


def test_get_passage_group_not_found(client):
    response = client.get("/passage-groups/not-a-real-group")

    assert response.status_code == 404
