"""Tests for /passage-groups -- the canon-structure taxonomy (Pentateuch,
Old/New Testament, ...), synced from passage_groups.yaml.
"""

import pytest

from theo.passage_groups import normalize_alias, resolve_alias_index


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


def test_get_passage_group_by_alias(client):
    # "Torah" is an alias of pentateuch; resolution is case-insensitive.
    response = client.get("/passage-groups/Torah")

    assert response.status_code == 200
    detail = response.json()
    assert detail["group"]["slug"] == "pentateuch"
    assert "Torah" in detail["aliases"]


def test_get_passage_group_by_name(client):
    response = client.get("/passage-groups/Old Testament")

    assert response.status_code == 200
    assert response.json()["group"]["slug"] == "old-testament"


# --- Alias validation (pure, no DB) -----------------------------------------

def test_normalize_alias_lowercases_and_strips():
    assert normalize_alias("  The TWELVE ") == "the twelve"


def test_resolve_alias_index_flattens_valid_aliases():
    triples = resolve_alias_index([{"slug": "a", "aliases": ["Alpha", "Beta"]}, {"slug": "b"}])
    assert triples == [("a", "Alpha", "alpha"), ("a", "Beta", "beta")]


def test_resolve_alias_index_rejects_slug_collision():
    with pytest.raises(ValueError, match="slug"):
        resolve_alias_index([{"slug": "gospels"}, {"slug": "x", "aliases": ["gospels"]}])


def test_resolve_alias_index_rejects_book_name_collision():
    with pytest.raises(ValueError, match="book name"):
        resolve_alias_index([{"slug": "x", "aliases": ["Genesis"]}])


def test_resolve_alias_index_rejects_duplicate_alias():
    with pytest.raises(ValueError, match="duplicates"):
        resolve_alias_index([{"slug": "a", "aliases": ["Foo"]}, {"slug": "b", "aliases": ["foo"]}])
