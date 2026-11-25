"""MatrixRun: cell shortfall, reuse, stats/compare/figures."""

from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

import tomli_w

from bench_run.config import (
    ConfigError,
    dump_toml,
    load_toml,
    resolve_config_path,
    resolve_matrix_config_path,
    section_name,
    workspace_root,
)
from bench_run.fingerprint import compute_fingerprint
from bench_run.fs import (
    read_json,
    read_manifest,
    read_metadata,
    read_metrics,
    utc_now_iso,
    write_manifest,
    write_metadata,
)
from bench_run.ledger.local import LocalFsLedger
from bench_run.layers.run import PreflightCancel, Run
from bench_run.reporting.matrix import rewrite_compare_and_figures, write_matrix_reports
from bench_run.sink.base import LogLine, ProgressLine, Scope
from bench_run.sink.local import LocalFsSink


def _is_distributed_ledger(ledger: Any) -> bool:
    return bool(getattr(ledger, "distributed", False))


class MatrixRun:
    def __init__(
        self,
        config: str | Path | dict,
        *,
        name: str | None = None,
        cell_ids: list[str] | None = None,
        ledger: Any | None = None,
        repeats: int | None = None,
        max_failures: int | None = None,
        log_to_console: bool = True,
        tty_bar: bool | None = None,
        sink: Any | None = None,
    ) -> None:
        self.ledger = ledger or LocalFsLedger()
        self.sink = sink or LocalFsSink(
            log_to_console=log_to_console,
            tty_bar=tty_bar,
        )
        self._cell_ids_filter = list(cell_ids) if cell_ids is not None else None
        self._config_path: Path | None = None
        self._scope: Scope | None = None

        if isinstance(config, dict):
            self._config_data = dict(config)
            self._config_stem = name or section_name(self._config_data, "matrix") or "matrix"
        else:
            try:
                resolved = resolve_matrix_config_path(config)
            except ConfigError:
                p = Path(config)
                resolved = p if p.is_absolute() else (workspace_root() / p)
                if not resolved.is_file():
                    raise
            self._config_path = resolved
            self._config_data = load_toml(resolved)
            self._config_stem = resolved.stem

        msec = dict(self._config_data.get("matrix") or {})
        self._name = name or msec.get("name") or self._config_stem
        self._repeats = int(repeats if repeats is not None else msec.get("repeats", 1))
        if max_failures is not None:
            self._max_failures = int(max_failures)
        elif "max_failures" in msec:
            self._max_failures = int(msec["max_failures"])
        else:
            self._max_failures = self._repeats
        self._figure_metrics = list(msec.get("figure_metrics") or [])
        cells = list(msec.get("cells") or [])
        self._cells_cfg = cells
        self._baseline_cell = msec.get("baseline_cell") or (cells[0]["id"] if cells else None)

        self._id: str | None = None
        self._dir: Path | None = None
        self._status = "constructed"
        self._manifest: dict[str, Any] = {}
        self._resuming = False

    @property
    def id(self) -> str:
        if self._id is None:
            raise RuntimeError("MatrixRun not opened")
        return self._id

    @property
    def dir(self) -> Path:
        if self._dir is None:
            raise RuntimeError("MatrixRun not opened")
        return self._dir

    @property
    def status(self) -> str:
        return self._status

    def __enter__(self) -> MatrixRun:
        self._open_new()
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def _bind_scope(self) -> Scope:
        assert self._id is not None
        self._scope = Scope(layer="matrix", id=self._id, dir=self._dir)
        return self._scope

    def _open_new(self) -> None:
        mid, path = self.ledger.allocate_matrix_dir(str(self._name))
        self._id = mid
        self._dir = path
        self._status = "running"
        self._bind_scope()
        now = utc_now_iso()
        dump_toml(self._config_data, path / "config.toml")
        (path / "log.txt").touch()
        meta = {
            "id": mid,
            "layer": "matrix",
            "status": "running",
            "config_stem": self._config_stem,
            "name": self._name,
            "created_at": now,
            "updated_at": now,
            "finished_at": None,
            "paths": {
                "dir": self.ledger._rel(path),
                "config": "config.toml",
                "log": "log.txt",
            },
        }
        write_metadata(path, meta)
        cells_out = []
        for cell in self._cells_cfg:
            cid = cell["id"]
            if self._cell_ids_filter is not None and cid not in self._cell_ids_filter:
                continue
            cells_out.append(
                {
                    "id": cid,
                    "config_stem": Path(str(cell.get("config", ""))).stem,
                    "fingerprint": None,
                    "status": "pending",
                    "target_repeats": self._repeats,
                    "completed_run_ids": [],
                    "failed_run_ids": [],
                    "cancelled_run_ids": [],
                    "reused_run_ids": [],
                }
            )
        self._manifest = {
            "matrix_id": mid,
            "config_stem": self._config_stem,
            "repeats": self._repeats,
            "max_failures": self._max_failures,
            "baseline_cell": self._baseline_cell,
            "cells": cells_out,
            "updated_at": now,
        }
        write_manifest(path, self._manifest)
        self.ledger.put_manifest(mid, self._manifest)

    def _save_manifest(self) -> None:
        self._manifest["updated_at"] = utc_now_iso()
        write_manifest(self.dir, self._manifest)
        self.ledger.put_manifest(self.id, self._manifest)

    def write_to_log(self, msg: str) -> None:
        if self._scope is None:
            return
        self.sink.emit(self._scope, LogLine(msg))

    def progress_line(self, msg: str) -> None:
        if self._scope is None:
            return
        self.sink.emit(self._scope, ProgressLine(msg))

    @contextmanager
    def progress_bar(
        self,
        total: int | None = None,
        *,
        title: str | None = None,
        console: bool | None = None,
        tty_bar: bool | None = None,
    ) -> Iterator[Any]:
        assert self._scope is not None
        with self.sink.progress_bar(
            self._scope, total, title=title, tty_bar=tty_bar
        ) as bar:
            yield bar

    def _cell_terminal_count(self, cell: dict[str, Any]) -> int:
        return (
            len(cell.get("completed_run_ids") or [])
            + len(cell.get("failed_run_ids") or [])
            + len(cell.get("cancelled_run_ids") or [])
        )

    def _progress_done(self) -> int:
        return sum(self._cell_terminal_count(c) for c in self._manifest.get("cells") or [])

    def _progress_total_target(self) -> int:
        """Upper bound: target_repeats per active cell (cancellations may finish early)."""
        n = 0
        for cell in self._manifest.get("cells") or []:
            if cell.get("status") == "cancelled" and not cell.get("completed_run_ids"):
                n += max(1, self._cell_terminal_count(cell))
                continue
            n += int(cell.get("target_repeats") or self._repeats)
        return max(n, self._progress_done())

    def _cell_cfg(self, cell_id: str) -> dict[str, Any]:
        for c in self._cells_cfg:
            if c["id"] == cell_id:
                return c
        raise KeyError(cell_id)

    def _resolve_cell_run_config(self, cell: dict[str, Any]) -> tuple[Path | dict, str, dict]:
        cfg_ref = cell.get("config")
        if cfg_ref is None:
            raise ConfigError(f"cell {cell.get('id')} missing config")
        path = resolve_config_path(cfg_ref)
        data = load_toml(path)
        return path, path.stem, data

    def _cell_params(self, cell: dict[str, Any], run_data: dict[str, Any]) -> dict[str, Any]:
        params = dict(run_data.get("params") or {})
        overlay = dict(cell.get("params") or {})
        params.update(overlay)
        return params

    def _cell_fingerprint(self, cell: dict[str, Any]) -> tuple[str, dict, dict, list[str]]:
        path, stem, data = self._resolve_cell_run_config(cell)
        params = self._cell_params(cell, data)
        keys = list((data.get("run") or {}).get("fingerprint_keys") or [])
        fp = compute_fingerprint(stem, params, keys)
        return fp, data, params, keys

    def execute(
        self,
        runner: Callable[[Run], None] | None = None,
        *,
        distributed: bool = False,
    ) -> MatrixRun:
        if self._dir is None:
            self._open_new()
        assert self._dir is not None and self._id is not None

        use_dist = (
            distributed
            or runner is None
            or _is_distributed_ledger(self.ledger)
        )
        if use_dist:
            return self._execute_distributed()

        assert runner is not None
        self.progress_line(
            f"matrix start id={self.id} cells={len(self._manifest['cells'])} "
            f"repeats={self._repeats}"
        )
        total = self._progress_total_target()
        with self.progress_bar(total, title=f"matrix:{self._name}") as bar:
            done = self._progress_done()
            for _ in range(done):
                bar()
            for cell_entry in self._manifest["cells"]:
                before = self._cell_terminal_count(cell_entry)
                self._drive_cell(cell_entry, runner)
                self._save_manifest()
                after = self._cell_terminal_count(cell_entry)
                for _ in range(max(0, after - before)):
                    bar()
                self.progress_line(
                    f"cell={cell_entry['id']} → {cell_entry['status']} "
                    f"completed={len(cell_entry['completed_run_ids'])}/{self._repeats}"
                )

        self._write_aggregates()
        self._status = "complete"
        now = utc_now_iso()
        meta = read_metadata(self.dir)
        meta["status"] = "complete"
        meta["finished_at"] = now
        write_metadata(self.dir, meta)
        self.progress_line(f"matrix complete id={self.id}")
        return self

    def _all_cells_terminal(self) -> bool:
        for cell in self._manifest["cells"]:
            st = cell.get("status")
            if st in ("ok", "failed", "cancelled", "partial"):
                continue
            if len(cell.get("completed_run_ids") or []) >= self._repeats:
                continue
            if len(cell.get("failed_run_ids") or []) >= self._max_failures:
                continue
            if cell.get("cancelled_run_ids"):
                continue
            return False
        return True

    def _enqueue_cell_shortfall(self, cell_entry: dict[str, Any]) -> None:
        cell_id = cell_entry["id"]
        cell_cfg = self._cell_cfg(cell_id)
        fp, run_data, params, _keys = self._cell_fingerprint(cell_cfg)
        cell_entry["fingerprint"] = fp
        cell_entry["config_stem"] = Path(str(cell_cfg.get("config", ""))).stem

        needed = self._repeats - len(cell_entry["completed_run_ids"])
        if needed > 0:
            found = self.ledger.find_completed_runs(fp, limit=needed)
            have = set(cell_entry["completed_run_ids"])
            for rid in found:
                if rid in have:
                    continue
                cell_entry["completed_run_ids"].append(rid)
                cell_entry["reused_run_ids"].append(rid)
                have.add(rid)
                if len(cell_entry["completed_run_ids"]) >= self._repeats:
                    break

        if len(cell_entry["completed_run_ids"]) >= self._repeats:
            cell_entry["status"] = "ok"
            return

        cell_entry["status"] = "running"
        in_flight = 0
        if hasattr(self.ledger, "queue"):
            try:
                in_flight = self.ledger.queue.in_flight_for_cell(self.id, cell_id)
            except Exception:
                in_flight = 0
        shortfall = self._repeats - len(cell_entry["completed_run_ids"]) - in_flight
        config_toml = tomli_w.dumps(run_data)
        for i in range(max(0, shortfall)):
            if len(cell_entry["failed_run_ids"]) >= self._max_failures:
                break
            repeat_index = (
                len(cell_entry["completed_run_ids"])
                + len(cell_entry["failed_run_ids"])
                + in_flight
                + i
            )
            parent = {
                "layer": "matrix",
                "id": self.id,
                "cell_id": cell_id,
                "repeat_index": repeat_index,
            }
            stem = cell_entry["config_stem"]
            rid, _path = self.ledger.allocate_run_dir(str(stem))
            spec = {
                "run_id": rid,
                "config_stem": stem,
                "config_toml": config_toml,
                "params": params,
                "fingerprint": fp,
                "handoff_artifacts": {},
                "parent": parent,
                "lease_s": 300,
                "name": (run_data.get("run") or {}).get("name") or stem,
            }
            self.ledger.create_run(spec)
            self.ledger.enqueue_run(spec)

    def _execute_distributed(self) -> MatrixRun:
        self.progress_line(
            f"matrix start (distributed) id={self.id} "
            f"cells={len(self._manifest['cells'])} repeats={self._repeats}"
        )
        for cell_entry in self._manifest["cells"]:
            if cell_entry.get("status") in ("ok", "cancelled"):
                continue
            self._enqueue_cell_shortfall(cell_entry)
            self._save_manifest()

        total = self._progress_total_target()
        last_line_at = 0.0
        with self.progress_bar(total, title=f"matrix:{self._name}") as bar:
            reported = 0
            done = self._progress_done()
            while reported < done:
                bar()
                reported += 1

            if not self._all_cells_terminal():
                while not self._all_cells_terminal():
                    self.ledger.wait_matrix_terminal(self.id, timeout_s=2.0)
                    try:
                        self._manifest = self.ledger.get_manifest(self.id)
                        write_manifest(self.dir, self._manifest)
                    except Exception:
                        pass
                    done = self._progress_done()
                    while reported < done:
                        bar()
                        reported += 1
                    now = time.monotonic()
                    if now - last_line_at >= 1.0:
                        last_line_at = now
                        cells = self._manifest.get("cells") or []
                        ok_n = sum(1 for c in cells if c.get("status") == "ok")
                        self.progress_line(
                            f"waiting cells_ok={ok_n}/{len(cells)} "
                            f"runs_done={done}/{total}"
                        )
                    if self._all_cells_terminal():
                        break

        try:
            self._manifest = self.ledger.get_manifest(self.id)
            write_manifest(self.dir, self._manifest)
        except Exception:
            pass

        for cell_entry in self._manifest.get("cells") or []:
            self.progress_line(
                f"cell={cell_entry['id']} → {cell_entry.get('status')} "
                f"completed={len(cell_entry.get('completed_run_ids') or [])}/{self._repeats}"
            )

        if not (self.dir / "stats.json").is_file():
            self._write_aggregates()

        self._status = "complete"
        now = utc_now_iso()
        meta = read_metadata(self.dir)
        meta["status"] = "complete"
        meta["finished_at"] = now
        write_metadata(self.dir, meta)
        if hasattr(self.ledger, "signal_matrix_terminal"):
            self.ledger.signal_matrix_terminal(self.id)
        self.progress_line(f"matrix complete id={self.id}")
        return self

    def _drive_cell(
        self,
        cell_entry: dict[str, Any],
        runner: Callable[[Run], None],
    ) -> None:
        cell_id = cell_entry["id"]
        cell_cfg = self._cell_cfg(cell_id)
        fp, run_data, params, _keys = self._cell_fingerprint(cell_cfg)
        cell_entry["fingerprint"] = fp
        cell_entry["config_stem"] = Path(str(cell_cfg.get("config", ""))).stem

        # reuse
        needed = self._repeats - len(cell_entry["completed_run_ids"])
        if needed > 0:
            found = self.ledger.find_completed_runs(fp, limit=needed)
            # exclude already listed
            have = set(cell_entry["completed_run_ids"])
            for rid in found:
                if rid in have:
                    continue
                cell_entry["completed_run_ids"].append(rid)
                cell_entry["reused_run_ids"].append(rid)
                have.add(rid)
                if len(cell_entry["completed_run_ids"]) >= self._repeats:
                    break

        if len(cell_entry["completed_run_ids"]) >= self._repeats:
            cell_entry["status"] = "ok"
            if cell_entry.get("reused_run_ids"):
                self.progress_line(
                    f"cell={cell_id} reuse filled "
                    f"completed={len(cell_entry['completed_run_ids'])}/{self._repeats}"
                )
            return

        cell_entry["status"] = "running"
        self._save_manifest()

        while (
            len(cell_entry["completed_run_ids"]) < self._repeats
            and len(cell_entry["failed_run_ids"]) < self._max_failures
            and cell_entry["status"] != "cancelled"
        ):
            repeat_index = len(cell_entry["completed_run_ids"]) + len(cell_entry["failed_run_ids"])
            parent = {
                "layer": "matrix",
                "id": self.id,
                "cell_id": cell_id,
                "repeat_index": repeat_index,
            }
            run = Run(
                run_data,
                name=(run_data.get("run") or {}).get("name") or cell_entry["config_stem"],
                ledger=self.ledger,
                sink=self.sink.with_options(tty_bar=False),
                parent=parent,
                params_overlay=dict(cell_cfg.get("params") or {}),
                fingerprint=fp,
            )
            run.__enter__()
            try:
                try:
                    run.preflight()
                except PreflightCancel:
                    cell_entry["cancelled_run_ids"].append(run.id)
                    cell_entry["status"] = "cancelled"
                    run.__exit__(PreflightCancel, PreflightCancel(), None)
                    self.progress_line(
                        f"cell={cell_id} run={run.id} status=cancelled"
                    )
                    break
                try:
                    runner(run)
                except Exception as exc:
                    run.__exit__(type(exc), exc, exc.__traceback__)
                    if run.status == "cancelled":
                        cell_entry["cancelled_run_ids"].append(run.id)
                        cell_entry["status"] = "cancelled"
                        self.progress_line(
                            f"cell={cell_id} run={run.id} status=cancelled"
                        )
                        break
                    cell_entry["failed_run_ids"].append(run.id)
                    self.progress_line(
                        f"cell={cell_id} run={run.id} status=failed"
                    )
                    self._save_manifest()
                    continue
                run.__exit__(None, None, None)
                if run.status == "complete":
                    cell_entry["completed_run_ids"].append(run.id)
                    self.progress_line(
                        f"cell={cell_id} run={run.id} status=complete "
                        f"completed={len(cell_entry['completed_run_ids'])}/{self._repeats}"
                    )
                elif run.status == "cancelled":
                    cell_entry["cancelled_run_ids"].append(run.id)
                    cell_entry["status"] = "cancelled"
                    self.progress_line(
                        f"cell={cell_id} run={run.id} status=cancelled"
                    )
                    break
                elif run.status == "failed":
                    cell_entry["failed_run_ids"].append(run.id)
                    self.progress_line(
                        f"cell={cell_id} run={run.id} status=failed"
                    )
                else:
                    cell_entry["failed_run_ids"].append(run.id)
                    self.progress_line(
                        f"cell={cell_id} run={run.id} status={run.status}"
                    )
            except PreflightCancel:
                cell_entry["status"] = "cancelled"
                if run.id not in cell_entry["cancelled_run_ids"]:
                    cell_entry["cancelled_run_ids"].append(run.id)
                break

            self._save_manifest()

        if cell_entry["status"] == "cancelled":
            return
        if len(cell_entry["completed_run_ids"]) >= self._repeats:
            cell_entry["status"] = "ok"
        elif len(cell_entry["failed_run_ids"]) >= self._max_failures:
            cell_entry["status"] = "failed"
        else:
            cell_entry["status"] = "partial"

    def _load_run_metrics_run(self, run_id: str) -> dict[str, Any]:
        try:
            d = self.ledger.run_dir(run_id)
        except KeyError:
            d = self.ledger.results / "run" / run_id
        if not d.is_dir():
            return {}
        metrics = read_metrics(d)
        return dict(metrics.get("run") or {})

    def _write_aggregates(self) -> None:
        cell_metrics: dict[str, list[dict[str, Any]]] = {}
        for cell in self._manifest["cells"]:
            runs = [self._load_run_metrics_run(rid) for rid in cell["completed_run_ids"]]
            cell_metrics[cell["id"]] = runs
        baseline = self._baseline_cell or (
            self._manifest["cells"][0]["id"] if self._manifest["cells"] else ""
        )
        stats, compare, figs = write_matrix_reports(
            self.dir,
            cell_metrics,
            baseline_cell=baseline,
            figure_metrics=self._figure_metrics or None,
        )
        self.ledger.put_matrix_stats(self.id, stats)
        self.ledger.put_matrix_compare(self.id, compare)
        for p in figs:
            try:
                self.ledger.put_matrix_figure(self.id, p.name, p.read_bytes())
            except Exception:
                pass

    def compare(self) -> dict[str, Any]:
        """Rebuild compare.json and figures from existing stats.json."""
        stats = read_json(self.dir / "stats.json")
        baseline = self._baseline_cell or (
            self._manifest.get("baseline_cell")
            or (self._manifest["cells"][0]["id"] if self._manifest.get("cells") else "")
        )
        return rewrite_compare_and_figures(
            self.dir,
            stats,
            baseline_cell=baseline,
            figure_metrics=self._figure_metrics or None,
        )

    @classmethod
    def resume(
        cls,
        dir: str | Path,
        *,
        ledger: Any | None = None,
        sink: Any | None = None,
        log_to_console: bool = True,
        tty_bar: bool | None = None,
    ) -> MatrixRun:
        d = Path(dir)
        meta = read_metadata(d)

        def _finish(m: MatrixRun) -> MatrixRun:
            m.sink = sink or LocalFsSink(
                log_to_console=log_to_console,
                tty_bar=tty_bar,
            )
            m._bind_scope()
            return m

        if meta.get("status") in ("complete", "cancelled"):
            m = cls.__new__(cls)
            m.ledger = ledger or LocalFsLedger()
            m.ledger.register_matrix_dir(meta["id"], d)
            m._id = meta["id"]
            m._dir = d
            m._status = meta["status"]
            m._config_data = load_toml(d / "config.toml")
            m._config_stem = meta.get("config_stem") or d.name
            m._name = meta.get("name") or m._config_stem
            m._manifest = read_manifest(d)
            m._repeats = m._manifest.get("repeats", 1)
            m._max_failures = m._manifest.get("max_failures", m._repeats)
            m._cells_cfg = list((m._config_data.get("matrix") or {}).get("cells") or [])
            m._baseline_cell = m._manifest.get("baseline_cell")
            m._figure_metrics = list((m._config_data.get("matrix") or {}).get("figure_metrics") or [])
            m._cell_ids_filter = None
            m._config_path = d / "config.toml"
            m._resuming = True
            return _finish(m)

        m = cls.__new__(cls)
        m.ledger = ledger or LocalFsLedger()
        m.ledger.register_matrix_dir(meta["id"], d)
        m._id = meta["id"]
        m._dir = d
        m._status = "running"
        m._config_data = load_toml(d / "config.toml")
        m._config_stem = meta.get("config_stem") or d.name
        m._name = meta.get("name") or m._config_stem
        m._manifest = read_manifest(d)
        m._repeats = m._manifest.get("repeats", 1)
        m._max_failures = m._manifest.get("max_failures", m._repeats)
        m._cells_cfg = list((m._config_data.get("matrix") or {}).get("cells") or [])
        m._baseline_cell = m._manifest.get("baseline_cell")
        m._figure_metrics = list((m._config_data.get("matrix") or {}).get("figure_metrics") or [])
        m._cell_ids_filter = None
        m._config_path = d / "config.toml"
        m._resuming = True
        meta["status"] = "running"
        write_metadata(d, meta)
        return _finish(m)
