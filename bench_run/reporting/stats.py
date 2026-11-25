"""Matrix stats.json from per-cell run metrics."""

from __future__ import annotations

import math
import statistics
from typing import Any


def _is_numeric(v: Any) -> bool:
    if isinstance(v, bool):
        return True
    if isinstance(v, (int, float)):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return False
        return True
    return False


def _as_float(v: Any) -> float:
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    return float(v)


def build_stats(cell_metrics: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Build stats.json structure from per-cell lists of metrics.run dicts.

    ``cell_metrics`` maps cell_id → list of ``metrics["run"]`` dicts (one per completed run).
    """
    cells_out: dict[str, Any] = {}
    for cell_id, runs in cell_metrics.items():
        n = len(runs)
        keys: set[str] = set()
        for r in runs:
            for k, v in r.items():
                if _is_numeric(v):
                    keys.add(k)
        cell_stats: dict[str, Any] = {"n": n}
        for key in sorted(keys):
            vals = [_as_float(r[key]) for r in runs if key in r and _is_numeric(r[key])]
            if not vals:
                continue
            mean = statistics.fmean(vals)
            if len(vals) < 2:
                std = 0.0
            else:
                std = statistics.stdev(vals)  # ddof=1
            cell_stats[key] = {"mean": mean, "std": std}
        cells_out[cell_id] = cell_stats
    return {"cells": cells_out}
