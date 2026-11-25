"""Local in-process drive: run / matrix / campaign + resume."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

from bench_run.config import workspace_root
from bench_run.fs import read_metadata
from bench_run.layers.campaign import CampaignRun
from bench_run.layers.matrix import MatrixRun
from bench_run.layers.run import PreflightCancel, Run
from bench_run.sink.local import LocalFsSink


def make_local_sink(*, log_to_console: bool, tty_bar: bool) -> LocalFsSink:
    return LocalFsSink(log_to_console=log_to_console, tty_bar=tty_bar)


def layer_exit_code(layer: Any) -> int:
    status = getattr(layer, "status", None)
    if status == "cancelled":
        return 3
    if status == "failed":
        return 2
    if hasattr(layer, "_manifest") and isinstance(getattr(layer, "_manifest", None), dict):
        cells = layer._manifest.get("cells") or []
        if cells:
            any_cancel = any(c.get("status") == "cancelled" for c in cells)
            any_fail = any(c.get("status") == "failed" for c in cells)
            any_ok = any(c.get("status") == "ok" for c in cells)
            if any_cancel and not any_ok:
                return 3
            if any_fail and not any_ok:
                return 2
    return 0


def _drive_run(
    path: Path,
    runner: Callable[[Run], None],
    *,
    name: str | None,
    log_to_console: bool,
    tty_bar: bool,
) -> int:
    sink = make_local_sink(log_to_console=log_to_console, tty_bar=tty_bar)
    try:
        with Run(path, name=name, sink=sink) as run:
            run.preflight()
            run.progress_line(f"run body start id={run.id}")
            with run.progress_bar(None, title=f"run:{run.config_stem}"):
                runner(run)
            run.progress_line(f"run body end status={run.status}")
        if run.status == "cancelled":
            return 3
        if run.status == "failed":
            return 2
        return 0
    except PreflightCancel:
        return 3


def _drive_matrix(
    path: Path,
    runner: Callable[[Run], None],
    *,
    name: str | None,
    cell_ids: list[str] | None,
    log_to_console: bool,
    tty_bar: bool,
) -> int:
    sink = make_local_sink(log_to_console=log_to_console, tty_bar=tty_bar)
    matrix = MatrixRun(
        path,
        name=name,
        cell_ids=cell_ids,
        sink=sink,
    )
    matrix.execute(runner)
    return layer_exit_code(matrix)


def _drive_campaign(
    path: Path,
    runner: Callable[[Run], None],
    *,
    name: str | None,
    phase_ids: list[str] | None,
    log_to_console: bool,
    tty_bar: bool,
) -> int:
    sink = make_local_sink(log_to_console=log_to_console, tty_bar=tty_bar)
    campaign = CampaignRun(
        path,
        name=name,
        phase_ids=phase_ids,
        sink=sink,
    )
    campaign.execute(runner)
    return layer_exit_code(campaign)


def run(
    experiment: Path,
    kind: str,
    data: dict,
    runner: Callable[[Run], None],
    *,
    name: str | None = None,
    cell_ids: list[str] | None = None,
    phase_ids: list[str] | None = None,
    log_to_console: bool = True,
    tty_bar: bool = True,
) -> int:
    """Drive a local experiment. ``data`` is unused today (path carries config)."""
    del data  # resolved by layer constructors from path
    try:
        if kind == "run":
            return _drive_run(
                experiment,
                runner,
                name=name,
                log_to_console=log_to_console,
                tty_bar=tty_bar,
            )
        if kind == "matrix":
            return _drive_matrix(
                experiment,
                runner,
                name=name,
                cell_ids=cell_ids,
                log_to_console=log_to_console,
                tty_bar=tty_bar,
            )
        if kind == "campaign":
            return _drive_campaign(
                experiment,
                runner,
                name=name,
                phase_ids=phase_ids,
                log_to_console=log_to_console,
                tty_bar=tty_bar,
            )
        print(f"error: unsupported config kind {kind!r} for local mode", file=sys.stderr)
        return 1
    except PreflightCancel:
        return 3


def resume(
    results_dir: Path | str,
    runner: Callable[[Run], None],
    *,
    log_to_console: bool = True,
    tty_bar: bool = True,
) -> int:
    d = Path(results_dir)
    if not d.is_absolute():
        d = workspace_root() / d
    if not d.is_dir():
        print(f"error: resume dir not found: {results_dir}", file=sys.stderr)
        return 1
    meta_path = d / "metadata.json"
    if not meta_path.is_file():
        print(f"error: no metadata.json in {results_dir}", file=sys.stderr)
        return 1

    meta = read_metadata(d)
    layer = meta.get("layer")
    status = meta.get("status")
    sink = make_local_sink(log_to_console=log_to_console, tty_bar=tty_bar)

    if layer == "run":
        if status in ("complete", "failed", "cancelled"):
            return 0
        run_obj = Run.resume(d, sink=sink)
        if run_obj is None:
            return 0
        try:
            with run_obj.progress_bar(None, title=f"run:{run_obj.config_stem}"):
                runner(run_obj)
            if run_obj.status == "running":
                run_obj.complete()
        except Exception as exc:
            run_obj.fail(exc)
            return 2
        return 0 if run_obj.status == "complete" else (3 if run_obj.status == "cancelled" else 2)

    if layer == "matrix":
        matrix = MatrixRun.resume(d, sink=sink)
        if matrix.status in ("complete", "cancelled"):
            return 0
        matrix.execute(runner)
        return layer_exit_code(matrix)

    if layer == "campaign":
        campaign = CampaignRun.resume(d, sink=sink)
        if campaign.status in ("complete", "cancelled"):
            return 0
        campaign.execute(runner)
        return layer_exit_code(campaign)

    print(f"error: unknown layer {layer!r}", file=sys.stderr)
    return 1
