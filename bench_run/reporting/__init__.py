"""Post-run reports: stats, compare, figures."""

from bench_run.reporting.compare import PREFERRED_FIGURE_METRICS, build_compare
from bench_run.reporting.figures import write_matrix_figures
from bench_run.reporting.matrix import rewrite_compare_and_figures, write_matrix_reports
from bench_run.reporting.stats import build_stats

__all__ = [
    "PREFERRED_FIGURE_METRICS",
    "build_stats",
    "build_compare",
    "write_matrix_figures",
    "write_matrix_reports",
    "rewrite_compare_and_figures",
]
