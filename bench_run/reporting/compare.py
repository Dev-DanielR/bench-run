"""Matrix compare.json from stats (baseline deltas + metric order)."""

from __future__ import annotations

from typing import Any

PREFERRED_FIGURE_METRICS = ["accuracy", "f1", "loss", "score"]


def build_compare(
    stats: dict[str, Any],
    *,
    baseline_cell: str,
    figure_metrics: list[str] | None = None,
) -> dict[str, Any]:
    cells = stats.get("cells") or {}
    metric_keys: set[str] = set()
    for cell_data in cells.values():
        for k, v in cell_data.items():
            if k == "n":
                continue
            if isinstance(v, dict) and "mean" in v:
                metric_keys.add(k)

    ordered: list[str] = []
    pref = list(figure_metrics) if figure_metrics else []
    if not pref:
        pref = [m for m in PREFERRED_FIGURE_METRICS if m in metric_keys]
    for m in pref:
        if m in metric_keys and m not in ordered:
            ordered.append(m)
    for m in sorted(metric_keys):
        if m not in ordered:
            ordered.append(m)

    baseline = cells.get(baseline_cell) or {}
    out_cells: dict[str, Any] = {}
    for cell_id, cell_data in cells.items():
        entry: dict[str, Any] = {}
        for m in ordered:
            raw = cell_data.get(m)
            if not isinstance(raw, dict) or "mean" not in raw:
                continue
            mean = raw["mean"]
            std = raw.get("std", 0.0)
            b_raw = baseline.get(m)
            b_mean = b_raw["mean"] if isinstance(b_raw, dict) and "mean" in b_raw else 0.0
            entry[m] = {"mean": mean, "std": std, "delta": mean - b_mean}
        out_cells[cell_id] = entry

    return {
        "baseline_cell": baseline_cell,
        "metrics": ordered,
        "cells": out_cells,
    }
