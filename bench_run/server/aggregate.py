"""Recompute matrix stats/compare/figures when cells become terminal."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bench_run.artifacts import (
    build_compare,
    build_stats,
    read_json,
    read_metrics,
    write_json,
)
from bench_run.figures import write_matrix_figures


def load_run_metrics(run_dir: Path) -> dict[str, Any]:
    if not run_dir.is_dir():
        return {}
    metrics = read_metrics(run_dir)
    return dict(metrics.get("run") or {})


def cell_is_terminal(cell: dict[str, Any], *, repeats: int, max_failures: int) -> bool:
    status = cell.get("status")
    if status in ("ok", "failed", "cancelled", "partial"):
        # partial only terminal if no more work expected
        if status == "partial":
            return True
        return True
    if cell.get("cancelled_run_ids"):
        return True
    if len(cell.get("completed_run_ids") or []) >= repeats:
        return True
    if len(cell.get("failed_run_ids") or []) >= max_failures:
        return True
    return False


def refresh_cell_status(cell: dict[str, Any], *, repeats: int, max_failures: int) -> None:
    if cell.get("cancelled_run_ids") and cell.get("status") == "cancelled":
        return
    if cell.get("status") == "cancelled":
        return
    if len(cell.get("cancelled_run_ids") or []) > 0 and cell.get("status") == "cancelled":
        return
    n_done = len(cell.get("completed_run_ids") or [])
    n_fail = len(cell.get("failed_run_ids") or [])
    if n_done >= repeats:
        cell["status"] = "ok"
    elif n_fail >= max_failures:
        cell["status"] = "failed"
    elif cell.get("cancelled_run_ids"):
        cell["status"] = "cancelled"


def matrix_all_terminal(manifest: dict[str, Any]) -> bool:
    repeats = int(manifest.get("repeats") or 1)
    max_failures = int(manifest.get("max_failures") or repeats)
    cells = manifest.get("cells") or []
    if not cells:
        return True
    for cell in cells:
        refresh_cell_status(cell, repeats=repeats, max_failures=max_failures)
        if not cell_is_terminal(cell, repeats=repeats, max_failures=max_failures):
            if cell.get("status") in ("pending", "running"):
                return False
            if cell.get("status") not in ("ok", "failed", "cancelled", "partial"):
                return False
    return True


def build_matrix_aggregates(
    matrix_dir: Path,
    manifest: dict[str, Any],
    *,
    run_dir_fn,
    figure_metrics: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[Path]]:
    """Write stats.json, compare.json, figures. Returns (stats, compare, fig_paths)."""
    cell_metrics: dict[str, list[dict[str, Any]]] = {}
    for cell in manifest.get("cells") or []:
        runs = []
        for rid in cell.get("completed_run_ids") or []:
            try:
                d = run_dir_fn(rid)
            except Exception:
                d = matrix_dir.parent.parent / "runs" / rid
            runs.append(load_run_metrics(Path(d)))
        cell_metrics[cell["id"]] = runs

    stats = build_stats(cell_metrics)
    write_json(matrix_dir / "stats.json", stats)

    baseline = manifest.get("baseline_cell") or (
        (manifest.get("cells") or [{}])[0].get("id") if manifest.get("cells") else ""
    )
    # figure_metrics from matrix config if present
    cfg_path = matrix_dir / "config.toml"
    fig_m = list(figure_metrics or [])
    if not fig_m and cfg_path.is_file():
        try:
            from bench_run.config import load_toml

            cfg = load_toml(cfg_path)
            fig_m = list((cfg.get("matrix") or {}).get("figure_metrics") or [])
        except Exception:
            pass

    compare = build_compare(stats, baseline_cell=baseline or "", figure_metrics=fig_m or None)
    write_json(matrix_dir / "compare.json", compare)
    figs = write_matrix_figures(matrix_dir / "figures", compare)
    return stats, compare, figs


def maybe_aggregate_matrix(store: Any, matrix_id: str) -> bool:
    """If all cells terminal, write aggregates and signal waiters. Returns True if terminal."""
    try:
        manifest = store.get_manifest(matrix_id)
    except KeyError:
        return False
    if not matrix_all_terminal(manifest):
        store.put_manifest(matrix_id, manifest)
        return False
    store.put_manifest(matrix_id, manifest)
    mdir = store.matrix_dir(matrix_id)
    stats, compare, figs = build_matrix_aggregates(
        mdir, manifest, run_dir_fn=store.run_dir
    )
    store.put_matrix_stats(matrix_id, stats)
    store.put_matrix_compare(matrix_id, compare)
    for p in figs:
        try:
            store.put_matrix_figure(matrix_id, p.name, p.read_bytes())
        except Exception:
            pass
    # mark matrix metadata complete
    from bench_run.artifacts import read_metadata, utc_now_iso, write_metadata

    try:
        meta = read_metadata(mdir)
        if meta.get("status") != "complete":
            meta["status"] = "complete"
            meta["finished_at"] = utc_now_iso()
            write_metadata(mdir, meta)
    except Exception:
        pass
    store.signal_matrix_terminal(matrix_id)
    return True
