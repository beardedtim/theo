def _group_id(client, group_name: str) -> str:
    groups = client.get("/people-groups").json()
    return next(g["id"] for g in groups if g["group_name"] == group_name)


def test_list_people_groups(client):
    response = client.get("/people-groups")

    assert response.status_code == 200
    names = [g["group_name"] for g in response.json()]
    assert "Tribe of Reuben" in names
    assert "Apostles" in names


def test_get_people_group_detail(client):
    group_id = _group_id(client, "Tribe of Reuben")

    response = client.get(f"/people-groups/{group_id}")

    assert response.status_code == 200
    detail = response.json()
    assert detail["group"]["group_name"] == "Tribe of Reuben"
    assert "Dathan" in [m["name"] for m in detail["members"]]


def test_get_people_group_not_found(client):
    response = client.get("/people-groups/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
