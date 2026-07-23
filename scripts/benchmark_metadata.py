"""CLI: score each pericope_annotations pipeline's extracted entities
against STEPBible's TIPNR tagging and print a Precision/Recall/F1 report.
See theo/metadata_benchmark.py for the ground-truth/matching rationale.

Usage:
    uv run -m scripts.benchmark_metadata
    uv run -m scripts.benchmark_metadata --pipelines en_core_web_trf+fastcoref/v1 --show-misses 15
    uv run -m scripts.benchmark_metadata --book Ruth   # quick smoke run on one book
"""

import tyro
from rich.console import Console
from rich.table import Table

from theo.metadata_benchmark import EntityReport, evaluate_entities, list_pipelines, worst

console = Console()


def _report_table(reports: list[EntityReport]) -> Table:
    table = Table(title="Entity extraction vs. STEP ground truth")
    table.add_column("pipeline")
    table.add_column("pericopes", justify="right")
    table.add_column("tp", justify="right")
    table.add_column("fp", justify="right")
    table.add_column("fn", justify="right")
    table.add_column("precision", justify="right")
    table.add_column("recall", justify="right")
    table.add_column("f1", justify="right")
    for r in reports:
        table.add_row(
            r.pipeline, str(r.n_pericopes), str(r.tp), str(r.fp), str(r.fn),
            f"{r.precision:.3f}", f"{r.recall:.3f}", f"{r.f1:.3f}",
        )
    return table


def _print_worst(report: EntityReport, by: str, limit: int) -> None:
    console.print(f"\n[bold]{report.pipeline}[/bold] -- worst {by}:")
    for outcome in worst(report, by=by, limit=limit):
        console.print(f"  [cyan]{outcome.pericope_title}[/cyan] {by}={sorted(getattr(outcome, by))}")


def main(
    pipelines: tuple[str, ...] = (),
    translation: str = "NIV",
    book: str | None = None,
    max_pericopes: int | None = None,
    show_misses: int = 0,
) -> None:
    """CLI: run the entity-extraction benchmark for one or more pipelines.

    Args:
        pipelines: Pipeline ids to score (default: every pipeline with stored annotations)
        translation: Translation the annotations were stored under
        book: Restrict to one book (number or name), for a quick smoke run
        max_pericopes: Cap the number of pericopes evaluated
        show_misses: Print up to this many worst-missed and worst-spurious pericopes per pipeline (0 disables)
    """
    chosen = list(pipelines) or list_pipelines()
    if not chosen:
        raise SystemExit("No pipelines found in pericope_annotations -- run an annotate_*.py script first.")

    reports = [
        evaluate_entities(pipeline, translation=translation, book=book, max_pericopes=max_pericopes)
        for pipeline in chosen
    ]
    console.print(_report_table(reports))

    if show_misses:
        for report in reports:
            _print_worst(report, "missed", show_misses)
            _print_worst(report, "spurious", show_misses)


if __name__ == "__main__":
    tyro.cli(main)
