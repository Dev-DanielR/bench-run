"""Read/write JSON artifacts: metadata, metrics, stats, compare, manifests."""

from __future__ import annotations

import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=False, ensure_ascii=True)
        f.write("\n")


def allocate_stamp_dir(parent: Path, stem: str) -> tuple[str, Path]:
    """Create unique ``YYYYMMDD_HHMMSS_<stem>[_N]`` under parent. Returns (id, path)."""
    parent.mkdir(parents=True, exist_ok=True)
    base = f"{utc_stamp()}_{stem}"
    candidate = parent / base
    if not candidate.exists():
        candidate.mkdir(parents=True, exist_ok=False)
        return base, candidate
    n = 2
    while True:
        name = f"{base}_{n}"
        candidate = parent / name
        if not candidate.exists():
            candidate.mkdir(parents=True, exist_ok=False)
            return name, candidate
        n += 1


def write_metadata(dir_path: Path, metadata: dict[str, Any]) -> None:
    metadata = dict(metadata)
    metadata["updated_at"] = utc_now_iso()
    write_json(dir_path / "metadata.json", metadata)


def read_metadata(dir_path: Path) -> dict[str, Any]:
    return read_json(dir_path / "metadata.json")


def write_metrics(dir_path: Path, metrics: dict[str, Any]) -> None:
    write_json(dir_path / "metrics.json", metrics)


def read_metrics(dir_path: Path) -> dict[str, Any]:
    p = dir_path / "metrics.json"
    if not p.is_file():
        return {"run": {}, "items": {}}
    return read_json(p)


def write_manifest(dir_path: Path, manifest: dict[str, Any]) -> None:
    manifest = dict(manifest)
    manifest["updated_at"] = utc_now_iso()
    write_json(dir_path / "manifest.json", manifest)


def read_manifest(dir_path: Path) -> dict[str, Any]:
    return read_json(dir_path / "manifest.json")


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


PREFERRED_FIGURE_METRICS = ["accuracy", "f1", "loss", "score"]


def build_compare(
    stats: dict[str, Any],
    *,
    baseline_cell: str,
    figure_metrics: list[str] | None = None,
) -> dict[str, Any]:
    cells = stats.get("cells") or {}
    # collect metric keys present
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
