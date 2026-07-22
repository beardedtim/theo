"""Interface for the canon-structure group taxonomy (Pentateuch, Old/New
Testament, ...): which books belong together, and how those groupings
nest. Hand-authored in passage_groups.yaml (tracked in git, like notes/),
synced into the `passage_groups`/`passage_group_members` tables by
ingest_passage_groups.py.

Distinct from theo.people_groups: this is about which books/passages
belong together, not biographical/theographic groups of people.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from psycopg.rows import dict_row

from theo.bible import BOOKS
from theo.db import get_connection

_COLUMNS = "id, slug, name, description, parent_group_id"


@dataclass(frozen=True)
class PassageGroup:
    id: str
    slug: str
    name: str
    description: str | None
    parent_group_id: str | None


@dataclass(frozen=True)
class PassageGroupDetail:
    group: PassageGroup
    books: list[int]                # every book covered by this group's members, expanded/deduped/sorted
    children: list[PassageGroup]    # groups whose parent is this group
    aliases: list[str]              # alternate names resolving to this group (as authored), sorted


def _row_to_group(row: dict) -> PassageGroup:
    return PassageGroup(
        id=str(row["id"]),
        slug=row["slug"],
        name=row["name"],
        description=row["description"],
        parent_group_id=str(row["parent_group_id"]) if row["parent_group_id"] else None,
    )


def _member_ranges(group: dict) -> list[tuple[int, int]]:
    """A groups.yaml entry's `books: [start, end]` or `members: [...]`,
    normalized to (book_start, book_end) ranges -- each `members` entry
    becomes its own (book, book) range, so non-contiguous groups just
    carry more rows."""
    if "books" in group:
        start, end = group["books"]
        return [(start, end)]
    return [(book, book) for book in group["members"]]


def normalize_alias(text: str) -> str:
    """The lookup key for an alias/name: lowercased, surrounding whitespace
    stripped. So "the twelve", "The Twelve" and " THE TWELVE " all collapse
    to the same key. Matches passage_group_aliases.alias_normalized."""
    return text.strip().lower()


def resolve_alias_index(groups: list[dict]) -> list[tuple[str, str, str]]:
    """Flatten every group's optional `aliases:` list into
    (group_slug, alias, normalized) triples, validating the conventions
    documented in passage_groups.yaml. Hard-fails (ValueError) rather than
    silently picking a winner when an alias:
      - is empty/blank,
      - duplicates another alias (case-insensitively, across all groups),
      - collides with any group slug, or
      - collides with any book name in theo.bible.BOOKS.
    The canonical slug/name are intentionally NOT required as aliases --
    lookups index them directly (see resolve_passage_group)."""
    slugs = {g["slug"] for g in groups}
    book_names = {normalize_alias(b) for b in BOOKS}

    triples: list[tuple[str, str, str]] = []
    seen: dict[str, str] = {}  # normalized alias -> slug that first claimed it
    for g in groups:
        for alias in g.get("aliases", []):
            norm = normalize_alias(alias)
            if not norm:
                raise ValueError(f"{g['slug']}: empty alias {alias!r}")
            if norm in slugs:
                raise ValueError(f"{g['slug']}: alias {alias!r} collides with a group slug")
            if norm in book_names:
                raise ValueError(f"{g['slug']}: alias {alias!r} collides with a book name in theo.bible.BOOKS")
            if norm in seen:
                raise ValueError(
                    f"{g['slug']}: alias {alias!r} duplicates one already claimed by {seen[norm]!r}"
                )
            seen[norm] = g["slug"]
            triples.append((g["slug"], alias, norm))
    return triples


def load_source(path: Path) -> list[dict]:
    """Parse passage_groups.yaml's top-level `groups:` list."""
    data = yaml.safe_load(Path(path).read_text())
    return data["groups"]


def sync_passage_groups(path: Path, prune: bool = False) -> tuple[int, int]:
    """Upsert every group in passage_groups.yaml into `passage_groups` +
    `passage_group_members`, keyed by slug.

    Safe to rerun after editing the file: edited groups (name,
    description, parent, book ranges) overwrite in place. Four passes,
    same reason as theo.people_groups' ingest -- a group's declared parent
    can appear later in the file, so parent_group_id needs every slug's id
    to already exist:
      1. Upsert scalar columns (slug/name/description).
      2. Resolve parent_group_id from each group's declared parent slug.
      3. Replace passage_group_members wholesale per group, so an edited
         book range converges correctly instead of accumulating stale rows.
      4. Replace passage_group_aliases wholesale per group (same reason).

    Aliases are validated up front (see resolve_alias_index): a collision
    with a slug/book name, or a duplicate alias, hard-fails before any
    write, so a bad edit is rejected atomically rather than half-applied.

    `prune=True` additionally deletes any group row whose slug is no
    longer in the file (off by default -- same rationale as
    theo.notes.sync_notes's `--prune`: only opt in when `path` is your
    real, complete file). Returns (upserted, deleted) counts.
    """
    groups = load_source(path)
    alias_triples = resolve_alias_index(groups)  # validates; raises before any write

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO passage_groups (slug, name, description)
                VALUES (%(slug)s, %(name)s, %(description)s)
                ON CONFLICT (slug) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description
                """,
                [
                    {"slug": g["slug"], "name": g["name"], "description": g.get("description")}
                    for g in groups
                ],
            )

            cur.execute("SELECT slug, id FROM passage_groups")
            slug_to_id = {row[0]: row[1] for row in cur.fetchall()}

            cur.executemany(
                "UPDATE passage_groups SET parent_group_id = %(parent_id)s WHERE id = %(id)s",
                [
                    {
                        "id": slug_to_id[g["slug"]],
                        "parent_id": slug_to_id[g["parent"]] if g.get("parent") else None,
                    }
                    for g in groups
                ],
            )

            for g in groups:
                group_id = slug_to_id[g["slug"]]
                cur.execute("DELETE FROM passage_group_members WHERE group_id = %s", (group_id,))
                cur.executemany(
                    "INSERT INTO passage_group_members (group_id, book_start, book_end) VALUES (%s, %s, %s)",
                    [(group_id, start, end) for start, end in _member_ranges(g)],
                )
                cur.execute("DELETE FROM passage_group_aliases WHERE group_id = %s", (group_id,))

            cur.executemany(
                """
                INSERT INTO passage_group_aliases (group_id, alias, alias_normalized)
                VALUES (%s, %s, %s)
                """,
                [(slug_to_id[slug], alias, norm) for slug, alias, norm in alias_triples],
            )

            deleted = 0
            if prune and groups:
                file_slugs = [g["slug"] for g in groups]
                cur.execute("DELETE FROM passage_groups WHERE NOT (slug = ANY(%s))", (file_slugs,))
                deleted = cur.rowcount
        conn.commit()

    return len(groups), deleted


def list_passage_groups() -> list[PassageGroup]:
    """Every passage group, alphabetical by name."""
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(f"SELECT {_COLUMNS} FROM passage_groups ORDER BY name")
            rows = cur.fetchall()
    return [_row_to_group(row) for row in rows]


def get_passage_group(slug: str) -> PassageGroup | None:
    """Fetch a single passage group by its slug, or None if it doesn't exist."""
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(f"SELECT {_COLUMNS} FROM passage_groups WHERE slug = %s", (slug,))
            row = cur.fetchone()
    return _row_to_group(row) if row else None


def resolve_passage_group(query: str) -> PassageGroup | None:
    """Resolve a group by slug, canonical name, or any alias -- all matched
    on the normalized key (see normalize_alias), so "pentateuch", "Torah"
    and " torah " all land on the same group. None if nothing matches.

    Aliases are globally unique and slugs/names never overlap an alias (the
    ingest guarantees both), so at most one group can match."""
    key = normalize_alias(query)
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT DISTINCT {', '.join('pg.' + c for c in _COLUMNS.split(', '))}
                FROM passage_groups pg
                LEFT JOIN passage_group_aliases a ON a.group_id = pg.id
                WHERE pg.slug = %(key)s
                   OR lower(btrim(pg.name)) = %(key)s
                   OR a.alias_normalized = %(key)s
                LIMIT 1
                """,
                {"key": key},
            )
            row = cur.fetchone()
    return _row_to_group(row) if row else None


def get_passage_group_detail(query: str) -> PassageGroupDetail | None:
    """A group plus its full expanded book list, any direct child groups,
    and its aliases, or None if nothing matches. `query` resolves by slug,
    name, or alias (see resolve_passage_group)."""
    group = resolve_passage_group(query)
    if group is None:
        return None

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT book_start, book_end FROM passage_group_members WHERE group_id = %s",
                (group.id,),
            )
            ranges = cur.fetchall()
            cur.execute(
                f"SELECT {_COLUMNS} FROM passage_groups WHERE parent_group_id = %s ORDER BY name",
                (group.id,),
            )
            children = cur.fetchall()
            cur.execute(
                "SELECT alias FROM passage_group_aliases WHERE group_id = %s ORDER BY alias",
                (group.id,),
            )
            aliases = [row["alias"] for row in cur.fetchall()]

    books = sorted({book for r in ranges for book in range(r["book_start"], r["book_end"] + 1)})
    return PassageGroupDetail(
        group=group,
        books=books,
        children=[_row_to_group(row) for row in children],
        aliases=aliases,
    )


def get_passage_groups_for_book(book: int) -> list[PassageGroup]:
    """Every passage group containing `book`, narrowest range first.

    Every group (leaf and container) restates its own full book coverage
    in passage_group_members (see artifacts/init.sql), so ordering by
    range width directly gives specific-before-general priority -- no need
    to walk parent_group_id. theo.metadata.resolve_attributes relies on
    this ordering for "most specific scope wins"."""
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT pg.id, pg.slug, pg.name, pg.description, pg.parent_group_id
                FROM passage_group_members gm
                JOIN passage_groups pg ON pg.id = gm.group_id
                WHERE %s BETWEEN gm.book_start AND gm.book_end
                ORDER BY (gm.book_end - gm.book_start) ASC, pg.name ASC
                """,
                (book,),
            )
            rows = cur.fetchall()
    return [_row_to_group(row) for row in rows]
