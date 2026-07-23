"""CLI: score theo.search's modes against benchmarks/search_golden_set.json
and print a Recall@5/@10 + MRR report. Build the golden set first with
`uv run -m scripts.build_search_golden_set`.

Usage:
    uv run -m scripts.benchmark_search
    uv run -m scripts.benchmark_search --modes hybrid --show-misses 15
    uv run -m scripts.benchmark_search --max-queries 40   # quick smoke run
"""

from pathlib import Path

import tyro
from rich.console import Console
from rich.table import Table

from theo.benchmark import DEFAULT_GOLDEN_SET_PATH, ModeReport, evaluate, load_golden_set, misses
from theo.search import SearchMode

console = Console()


def _report_table(reports: dict[str, ModeReport], k_values: tuple[int, ...]) -> Table:
    table = Table(title="Search benchmark")
    table.add_column("mode")
    table.add_column("n", justify="right")
    for k in k_values:
        table.add_column(f"Recall@{k}", justify="right")
    table.add_column("MRR", justify="right")

    for mode, report in reports.items():
        table.add_row(
            mode,
            str(report.n),
            *(f"{report.recall_at[k]:.3f}" for k in k_values),
            f"{report.mrr:.3f}",
        )
    return table


def _print_misses(report: ModeReport, k: int, limit: int) -> None:
    console.print(f"\n[bold]{report.mode}[/bold] misses (gold pericope absent from top {k}):")
    for outcome in misses(report, k=k)[:limit]:
        gold = outcome.query
        expected = " / ".join(gold.pericope_titles)
        retrieved = " / ".join(outcome.retrieved_titles[:3]) or "(nothing)"
        console.print(f"  [cyan]{gold.query!r}[/cyan] ({gold.reference}) expected [green]{expected}[/green], got {retrieved}")


def main(
    golden_set: Path = DEFAULT_GOLDEN_SET_PATH,
    modes: tuple[SearchMode, ...] = ("semantic", "bm25", "hybrid"),
    translation: str = "NIV",
    max_queries: int | None = None,
    show_misses: int = 0,
    focus_mode: SearchMode = "hybrid",
) -> None:
    """CLI: run the search golden set through theo.search and report Recall@k/MRR.

    Args:
        golden_set: Path to the golden set JSON built by build_search_golden_set.py
        modes: Which theo.search modes to score
        translation: Translation to search against
        max_queries: Cap the number of golden queries evaluated, for a quick smoke run
        show_misses: Print up to this many complete misses (0 disables)
        focus_mode: Which mode's misses to print when show_misses > 0
    """
    if not golden_set.exists():
        raise SystemExit(f"{golden_set} not found -- run `uv run -m scripts.build_search_golden_set` first.")

    queries = load_golden_set(golden_set)
    if max_queries is not None:
        queries = queries[:max_queries]
    if not queries:
        raise SystemExit(f"{golden_set} has no golden queries.")

    k_values = (5, 10)
    reports = evaluate(queries, modes=modes, translation=translation, k_values=k_values)

    console.print(_report_table(reports, k_values))

    if show_misses:
        _print_misses(reports[focus_mode], k=max(k_values), limit=show_misses)


if __name__ == "__main__":
    tyro.cli(main)
