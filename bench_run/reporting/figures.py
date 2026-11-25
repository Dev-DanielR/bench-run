"""Best-effort matplotlib Agg bar charts for matrix compare."""

from __future__ import annotations

import logging
import warnings
from pathlib import Path
from typing import Any

log = logging.getLogger("bench_run.reporting.figures")


def write_matrix_figures(
    figures_dir: Path,
    compare: dict[str, Any],
    *,
    warn: bool = True,
) -> list[Path]:
    """Write ``{metric}.png`` bar charts. Returns paths written; empty on failure."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # pragma: no cover - env dependent
        if warn:
            log.warning("matplotlib unavailable; skipping figures: %s", exc)
        return []

    figures_dir.mkdir(parents=True, exist_ok=True)
    metrics = list(compare.get("metrics") or [])
    cells = compare.get("cells") or {}
    cell_ids = list(cells.keys())
    n_cells = max(len(cell_ids), 1)
    written: list[Path] = []

    for metric in metrics:
        means: list[float] = []
        stds: list[float] = []
        labels: list[str] = []
        for cid in cell_ids:
            entry = (cells.get(cid) or {}).get(metric)
            if not isinstance(entry, dict) or "mean" not in entry:
                continue
            labels.append(cid)
            means.append(float(entry["mean"]))
            stds.append(float(entry.get("std") or 0.0))
        if not labels:
            continue
        try:
            fig, ax = plt.subplots(figsize=(max(6, 1.2 * n_cells), 4))
            ax.bar(labels, means, yerr=stds, capsize=4)
            ax.set_title(metric)
            ax.set_xlabel("cell id")
            ax.set_ylabel(metric)
            ax.grid(True, axis="y", alpha=0.3)
            out = figures_dir / f"{metric}.png"
            fig.savefig(out, dpi=120, bbox_inches="tight")
            plt.close(fig)
            written.append(out)
        except Exception as exc:  # pragma: no cover
            if warn:
                log.warning("failed to write figure for %s: %s", metric, exc)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    plt.close("all")
                except Exception:
                    pass
    return written
