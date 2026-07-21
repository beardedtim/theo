"""Search-quality benchmark: derive a "query -> relevant pericope(s)" golden
set from Theographic event data (free ground truth, no hand-labeling), then
score theo.search's modes against it with Recall@k and MRR.

An event's title is a short, human-phrased description of a Bible episode
(e.g. "Cain kills Abel", "The Baptism of Jesus") and its `event_verses` rows
pin down exactly which verses narrate it. Events whose verses fall inside a
single book, within a tight chapter span, and overlap only a handful of
pericopes look like a single retrievable passage -- broader events (e.g.
"Reign of Hezekiah" spanning 7 pericopes, or a theme like "Creation of all
things" tagged across dozens of scattered cross-references) describe a
topic rather than a passage, and are excluded so the golden set stays a
passage-retrieval benchmark rather than a topic-coverage one.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from theo.bible import book_name
from theo.db import get_connection
from theo.pericopes import get_pericopes_in_range
from theo.search import SearchMode, search as run_search

DEFAULT_GOLDEN_SET_PATH = Path("benchmarks/search_golden_set.json")

MAX_CHAPTER_SPAN = 2  # widest (chapter_end - chapter_start) an event may span
MAX_RELEVANT_PERICOPES = 3  # widest pericope-overlap count kept as a single query


@dataclass(frozen=True)
class GoldQuery:
    event_id: str
    query: str
    reference: str
    book: int
    chapter_start: int
    verse_start: int
    chapter_end: int
    verse_end: int
    pericope_ids: list[str]
    pericope_titles: list[str]


def build_golden_set(
    max_chapter_span: int = MAX_CHAPTER_SPAN,
    max_relevant_pericopes: int = MAX_RELEVANT_PERICOPES,
) -> list[GoldQuery]:
    """Derive golden queries from `events`/`event_verses`. See module docstring
    for the filtering rationale."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ev.id, ev.title, ev.sort_key, vr.book, vr.chapt_num, vr.verse_num
                FROM events ev JOIN event_verses vr ON vr.event_id = ev.id
                """
            )
            rows = cur.fetchall()

    coords_by_event: dict[str, list[tuple[int, int, int]]] = {}
    titles: dict[str, str] = {}
    sort_keys: dict[str, float] = {}
    for event_id, title, sort_key, book, chapter, verse in rows:
        coords_by_event.setdefault(str(event_id), []).append((book, chapter, verse))
        titles[str(event_id)] = title
        sort_keys[str(event_id)] = sort_key

    queries: list[GoldQuery] = []
    for event_id, coords in coords_by_event.items():
        books = {c[0] for c in coords}
        if len(books) != 1:
            continue  # spans multiple books -- not a single passage
        book = next(iter(books))
        lo_chapter, lo_verse = min(coords)[1:]
        hi_chapter, hi_verse = max(coords)[1:]
        if hi_chapter - lo_chapter > max_chapter_span:
            continue

        pericopes = get_pericopes_in_range(book, lo_chapter, lo_verse, hi_chapter, hi_verse)
        if not pericopes or len(pericopes) > max_relevant_pericopes:
            continue

        reference = f"{book_name(book)} {lo_chapter}:{lo_verse}-{hi_chapter}:{hi_verse}"
        queries.append(
            GoldQuery(
                event_id=event_id,
                query=titles[event_id],
                reference=reference,
                book=book,
                chapter_start=lo_chapter,
                verse_start=lo_verse,
                chapter_end=hi_chapter,
                verse_end=hi_verse,
                pericope_ids=[p.id for p in pericopes],
                pericope_titles=[p.title for p in pericopes],
            )
        )

    queries.sort(key=lambda q: sort_keys[q.event_id])
    return queries


def save_golden_set(queries: list[GoldQuery], path: Path = DEFAULT_GOLDEN_SET_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(q) for q in queries], indent=2, ensure_ascii=False) + "\n")


def load_golden_set(path: Path = DEFAULT_GOLDEN_SET_PATH) -> list[GoldQuery]:
    data = json.loads(path.read_text())
    return [GoldQuery(**row) for row in data]


# --- Evaluation ----------------------------------------------------------


@dataclass(frozen=True)
class QueryOutcome:
    query: GoldQuery
    retrieved_ids: list[str]
    retrieved_titles: list[str]
    recall_at: dict[int, float]
    reciprocal_rank: float


@dataclass(frozen=True)
class ModeReport:
    mode: str
    n: int
    recall_at: dict[int, float]  # k -> mean recall@k across all queries
    mrr: float
    outcomes: list[QueryOutcome]


def _recall_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    if not relevant_ids:
        return 0.0
    hits = len(set(retrieved_ids[:k]) & relevant_ids)
    return hits / len(relevant_ids)


def _reciprocal_rank(retrieved_ids: list[str], relevant_ids: set[str]) -> float:
    for rank, pericope_id in enumerate(retrieved_ids, start=1):
        if pericope_id in relevant_ids:
            return 1.0 / rank
    return 0.0


def evaluate_mode(
    queries: list[GoldQuery],
    mode: SearchMode,
    translation: str = "NIV",
    k_values: tuple[int, ...] = (5, 10),
) -> ModeReport:
    """Run every golden query through theo.search.search(mode=mode) and score
    Recall@k (for each k in k_values) and MRR against its gold pericope(s)."""
    limit = max(k_values)
    outcomes: list[QueryOutcome] = []
    for gold in queries:
        results = run_search(gold.query, mode=mode, translation=translation, limit=limit)
        retrieved_ids = [r.pericope.id for r in results]
        retrieved_titles = [r.pericope.title for r in results]
        relevant_ids = set(gold.pericope_ids)
        recall_at = {k: _recall_at_k(retrieved_ids, relevant_ids, k) for k in k_values}
        outcomes.append(
            QueryOutcome(
                query=gold,
                retrieved_ids=retrieved_ids,
                retrieved_titles=retrieved_titles,
                recall_at=recall_at,
                reciprocal_rank=_reciprocal_rank(retrieved_ids, relevant_ids),
            )
        )

    n = len(outcomes)
    mean_recall_at = {k: (sum(o.recall_at[k] for o in outcomes) / n if n else 0.0) for k in k_values}
    mrr = sum(o.reciprocal_rank for o in outcomes) / n if n else 0.0
    return ModeReport(mode=mode, n=n, recall_at=mean_recall_at, mrr=mrr, outcomes=outcomes)


def evaluate(
    queries: list[GoldQuery],
    modes: tuple[SearchMode, ...] = ("semantic", "bm25", "hybrid"),
    translation: str = "NIV",
    k_values: tuple[int, ...] = (5, 10),
) -> dict[str, ModeReport]:
    return {mode: evaluate_mode(queries, mode, translation=translation, k_values=k_values) for mode in modes}


def misses(report: ModeReport, k: int | None = None) -> list[QueryOutcome]:
    """Outcomes with zero recall at `k` (default: the largest k evaluated) --
    the gold pericope(s) never appeared anywhere in the retrieved list. Pass
    a smaller `k` to also flag "found, but not ranked soon enough"."""
    if k is None:
        k = max(report.recall_at) if report.recall_at else 0
    return [o for o in report.outcomes if o.recall_at.get(k, 0.0) == 0.0]
