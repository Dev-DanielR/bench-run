"""Write matrix stats.json, compare.json, and figures from cell metrics."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bench_run.fs import write_json
from bench_run.reporting.compare import build_compare
from bench_run.reporting.figures import write_matrix_figures
from bench_run.reporting.stats import build_stats


def write_matrix_reports(
    matrix_dir: Path,
    cell_metrics: dict[str, list[dict[str, Any]]],
    *,
    baseline_cell: str,
    figure_metrics: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[Path]]:
    """Build and write stats/compare/figures. Returns (stats, compare, fig_paths)."""
    stats = build_stats(cell_metrics)
    write_json(matrix_dir / "stats.json", stats)
    compare = build_compare(
        stats,
        baseline_cell=baseline_cell,
        figure_metrics=figure_metrics,
    )
    write_json(matrix_dir / "compare.json", compare)
    figs = write_matrix_figures(matrix_dir / "figures", compare)
    return stats, compare, figs


def rewrite_compare_and_figures(
    matrix_dir: Path,
    stats: dict[str, Any],
    *,
    baseline_cell: str,
    figure_metrics: list[str] | None = None,
) -> dict[str, Any]:
    """Rebuild compare.json and figures from existing stats."""
    compare = build_compare(
        stats,
        baseline_cell=baseline_cell,
        figure_metrics=figure_metrics,
    )
    write_json(matrix_dir / "compare.json", compare)
    write_matrix_figures(matrix_dir / "figures", compare)
    return compare
