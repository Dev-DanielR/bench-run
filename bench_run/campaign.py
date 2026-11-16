"""CampaignRun: phases, selectWinner, handoff."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Callable

from bench_run.artifacts import (
    read_json,
    read_manifest,
    read_metadata,
    utc_now_iso,
    write_json,
    write_manifest,
    write_metadata,
)
from bench_run.config import (
    ConfigError,
    dump_toml,
    load_toml,
    resolveCampaignConfigPath,
    resolveMatrixConfigPath,
    section_name,
    workspace_root,
)
from bench_run.ledger.local import LocalFsLedger
from bench_run.matrix import MatrixRun
from bench_run.run import PreflightCancel, Run


class CampaignRun:
    def __init__(
        self,
        config: str | Path | dict,
        *,
        name: str | None = None,
        phase_ids: list[int | str] | None = None,
        ledger: Any | None = None,
    ) -> None:
        self.ledger = ledger or LocalFsLedger()
        self._phase_ids_filter = (
            {str(p) for p in phase_ids} if phase_ids is not None else None
        )

        if isinstance(config, dict):
            self._config_data = dict(config)
            self._config_stem = name or section_name(self._config_data, "campaign") or "campaign"
        else:
            try:
                resolved = resolveCampaignConfigPath(config)
            except ConfigError:
                p = Path(config)
                resolved = p if p.is_absolute() else (workspace_root() / p)
                if not resolved.is_file():
                    raise
            self._config_path = resolved
            self._config_data = load_toml(resolved)
            self._config_stem = resolved.stem

        csec = dict(self._config_data.get("campaign") or {})
        self._name = name or csec.get("name") or self._config_stem
        self._repeats = csec.get("repeats")
        self._max_failures = csec.get("max_failures")
        self._continue_on_fail = bool(csec.get("continue_on_fail", False))
        self._phases_cfg = list(csec.get("phases") or [])

        self._id: str | None = None
        self._dir: Path | None = None
        self._status = "constructed"
        self._manifest: dict[str, Any] = {}
        self._handoff: dict[str, Any] = {"params": {}, "artifacts": {}, "by_phase": {}}
        self._winners: dict[str, Any] = {"phases": {}}
        self._resuming = False

    @property
    def id(self) -> str:
        if self._id is None:
            raise RuntimeError("CampaignRun not opened")
        return self._id

    @property
    def dir(self) -> Path:
        if self._dir is None:
            raise RuntimeError("CampaignRun not opened")
        return self._dir

    @property
    def status(self) -> str:
        return self._status

    def __enter__(self) -> CampaignRun:
        self._open_new()
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def _open_new(self) -> None:
        cid, path = self.ledger.allocate_campaign_dir(str(self._name))
        self._id = cid
        self._dir = path
        self._status = "running"
        now = utc_now_iso()
        dump_toml(self._config_data, path / "config.toml")
        (path / "log.txt").touch()
        meta = {
            "id": cid,
            "layer": "campaign",
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
        phases = []
        for ph in self._phases_cfg:
            pid = ph["id"]
            status = "pending"
            if self._phase_ids_filter is not None and str(pid) not in self._phase_ids_filter:
                status = "skipped"
            phases.append(
                {
                    "id": pid,
                    "name": ph.get("name"),
                    "matrix_stem": Path(str(ph.get("matrix", ""))).stem,
                    "matrix_id": None,
                    "status": status,
                    "winner_cell": None,
                    "winner_metric": ph.get("winner_metric"),
                }
            )
        self._manifest = {
            "campaign_id": cid,
            "config_stem": self._config_stem,
            "phases": phases,
            "updated_at": now,
        }
        write_manifest(path, self._manifest)
        self.ledger.put_campaign_manifest(cid, self._manifest)
        self._handoff = {"params": {}, "artifacts": {}, "by_phase": {}}
        self._winners = {"phases": {}}
        write_json(path / "handoff.json", self._handoff)
        write_json(path / "winners.json", self._winners)

    def _save_manifest(self) -> None:
        self._manifest["updated_at"] = utc_now_iso()
        write_manifest(self.dir, self._manifest)
        self.ledger.put_campaign_manifest(self.id, self._manifest)

    def _save_handoff(self) -> None:
        write_json(self.dir / "handoff.json", self._handoff)
        self.ledger.put_handoff(self.id, self._handoff)

    def _save_winners(self) -> None:
        write_json(self.dir / "winners.json", self._winners)
        self.ledger.put_winners(self.id, self._winners)

    def execute(
        self,
        runner: Callable[[Run], None] | None = None,
        *,
        distributed: bool = False,
    ) -> CampaignRun:
        if self._dir is None:
            self._open_new()

        use_dist = distributed or runner is None or bool(
            getattr(self.ledger, "distributed", False)
        )

        halted = False
        halt_status = "complete"

        for phase_entry, phase_cfg in zip(self._manifest["phases"], self._phases_cfg):
            if phase_entry["status"] == "skipped":
                continue
            if phase_entry["status"] == "ok":
                continue
            if halted:
                break

            phase_entry["status"] = "running"
            self._save_manifest()

            try:
                result = self._run_phase(
                    phase_entry, phase_cfg, runner, distributed=use_dist
                )
            except PreflightCancel:
                phase_entry["status"] = "cancelled"
                self._save_manifest()
                halted = True
                halt_status = "cancelled"
                break

            if result == "cancelled":
                phase_entry["status"] = "cancelled"
                self._save_manifest()
                halted = True
                halt_status = "cancelled"
                break
            if result == "failed":
                phase_entry["status"] = "failed"
                self._save_manifest()
                if not self._continue_on_fail:
                    halted = True
                    halt_status = "failed"
                    break
                continue
            # ok
            phase_entry["status"] = "ok"
            self._save_manifest()

        self._status = halt_status if halted else "complete"
        now = utc_now_iso()
        meta = read_metadata(self.dir)
        meta["status"] = self._status
        meta["finished_at"] = now
        write_metadata(self.dir, meta)
        self._save_handoff()
        self._save_winners()
        return self

    def _run_phase(
        self,
        phase_entry: dict[str, Any],
        phase_cfg: dict[str, Any],
        runner: Callable[[Run], None] | None,
        *,
        distributed: bool = False,
    ) -> str:
        """Returns 'ok' | 'failed' | 'cancelled'."""
        matrix_ref = phase_cfg["matrix"]
        try:
            mpath = resolveMatrixConfigPath(matrix_ref)
        except ConfigError:
            mpath = Path(matrix_ref)
            if not mpath.is_absolute():
                mpath = workspace_root() / mpath
        mdata = load_toml(mpath)

        # apply handoff params onto each cell
        mdata = self._apply_handoff_to_matrix(mdata)

        repeats = int(self._repeats) if self._repeats is not None else None
        max_failures = int(self._max_failures) if self._max_failures is not None else None

        # materialize handoff artifacts for runs
        handoff_paths = self._materialized_handoff_artifacts()

        matrix = MatrixRun(
            mdata,
            name=(mdata.get("matrix") or {}).get("name") or mpath.stem,
            ledger=self.ledger,
            repeats=repeats,
            max_failures=max_failures,
        )
        matrix._open_new()
        phase_entry["matrix_id"] = matrix.id
        self._save_manifest()

        if distributed or runner is None:
            # attach handoff artifact refs onto enqueued specs via template remember
            # workers download via RunSpec; put relative paths into templates after enqueue
            # For distributed: enqueue with handoff_artifacts map
            _orig_enqueue = matrix._enqueue_cell_shortfall

            def enqueue_with_handoff(cell_entry: dict[str, Any]) -> None:
                _orig_enqueue(cell_entry)
                if not handoff_paths:
                    return
                # update queued specs' handoff — best-effort via templates
                arts = {}
                for stem, src in handoff_paths.items():
                    rel = str(src.relative_to(self.dir)).replace("\\", "/") if src.is_relative_to(self.dir) else str(src)
                    # prefer store-relative under campaign
                    if hasattr(self.ledger, "data_dir"):
                        try:
                            rel = str(src.resolve().relative_to(self.ledger.data_dir.resolve())).replace("\\", "/")
                        except Exception:
                            rel = f"campaigns/{self.id}/" + str(src.relative_to(self.dir)).replace("\\", "/")
                    arts[stem] = {"path": rel, "sha256": ""}
                if hasattr(self.ledger, "remember_spec_template"):
                    tmpl = (getattr(self.ledger, "_spec_templates", {}).get(matrix.id) or {}).get(
                        cell_entry["id"]
                    )
                    if tmpl is not None:
                        tmpl["handoff_artifacts"] = arts
                        self.ledger.remember_spec_template(matrix.id, cell_entry["id"], tmpl)
                # also patch pending queue specs
                if hasattr(self.ledger, "queue"):
                    with self.ledger.queue.lock:
                        for spec in self.ledger.queue.pending:
                            parent = spec.get("parent") or {}
                            if parent.get("id") == matrix.id and parent.get("cell_id") == cell_entry["id"]:
                                spec["handoff_artifacts"] = arts

            matrix._enqueue_cell_shortfall = enqueue_with_handoff  # type: ignore[method-assign]
            matrix.execute(None, distributed=True)
        else:
            self._run_phase_local(matrix, phase_entry, runner, handoff_paths)

        # check cancel dominance
        for cell in matrix._manifest["cells"]:
            if cell["status"] == "cancelled":
                return "cancelled"

        any_failed = any(c["status"] == "failed" for c in matrix._manifest["cells"])
        all_ok = all(c["status"] == "ok" for c in matrix._manifest["cells"])
        if not all_ok and any_failed:
            pass

        winner = self.selectWinner(matrix, phase_cfg)
        if winner is None:
            return "failed"

        phase_entry["winner_cell"] = winner["cell_id"]
        self._winners["phases"][str(phase_entry["id"])] = winner
        self._save_winners()
        self._merge_handoff(phase_entry, phase_cfg, matrix, winner["cell_id"])
        return "ok"

    def _run_phase_local(
        self,
        matrix: MatrixRun,
        phase_entry: dict[str, Any],
        runner: Callable[[Run], None],
        handoff_paths: dict[str, Path],
    ) -> None:
        def phase_runner(run: Run) -> None:
            if handoff_paths and not run.handoff_artifacts:
                handoff_dir = run.dir / "handoff"
                handoff_dir.mkdir(parents=True, exist_ok=True)
                for stem, src in handoff_paths.items():
                    dest = handoff_dir / src.name
                    if src.is_file():
                        shutil.copy2(src, dest)
                        run.handoff_artifacts[stem] = dest
            runner(run)

        def drive_with_handoff(cell_entry: dict[str, Any], r: Callable[[Run], None]) -> None:
            cell_id = cell_entry["id"]
            cell_cfg = matrix._cell_cfg(cell_id)
            fp, run_data, params, _keys = matrix._cell_fingerprint(cell_cfg)
            cell_entry["fingerprint"] = fp
            cell_entry["config_stem"] = Path(str(cell_cfg.get("config", ""))).stem

            needed = matrix._repeats - len(cell_entry["completed_run_ids"])
            if needed > 0:
                found = matrix.ledger.find_completed_runs(fp, limit=needed)
                have = set(cell_entry["completed_run_ids"])
                for rid in found:
                    if rid in have:
                        continue
                    cell_entry["completed_run_ids"].append(rid)
                    cell_entry["reused_run_ids"].append(rid)
                    have.add(rid)
                    if len(cell_entry["completed_run_ids"]) >= matrix._repeats:
                        break

            if len(cell_entry["completed_run_ids"]) >= matrix._repeats:
                cell_entry["status"] = "ok"
                return

            cell_entry["status"] = "running"
            matrix._save_manifest()

            while (
                len(cell_entry["completed_run_ids"]) < matrix._repeats
                and len(cell_entry["failed_run_ids"]) < matrix._max_failures
                and cell_entry["status"] != "cancelled"
            ):
                repeat_index = (
                    len(cell_entry["completed_run_ids"]) + len(cell_entry["failed_run_ids"])
                )
                parent = {
                    "layer": "matrix",
                    "id": matrix.id,
                    "cell_id": cell_id,
                    "repeat_index": repeat_index,
                    "campaign_id": self.id,
                    "phase_id": phase_entry["id"],
                }
                run: Run | None = None
                try:
                    run = Run(
                        run_data,
                        name=(run_data.get("run") or {}).get("name") or cell_entry["config_stem"],
                        ledger=self.ledger,
                        parent=parent,
                        params_overlay=dict(cell_cfg.get("params") or {}),
                        handoff_artifacts=handoff_paths or None,
                        fingerprint=fp,
                    )
                    run.__enter__()
                    try:
                        run.preflight()
                    except PreflightCancel:
                        cell_entry["cancelled_run_ids"].append(run.id)
                        cell_entry["status"] = "cancelled"
                        run.__exit__(PreflightCancel, PreflightCancel(), None)
                        break
                    try:
                        r(run)
                    except Exception as exc:
                        run.__exit__(type(exc), exc, exc.__traceback__)
                        if run.status == "failed":
                            cell_entry["failed_run_ids"].append(run.id)
                        elif run.status == "cancelled":
                            cell_entry["cancelled_run_ids"].append(run.id)
                            cell_entry["status"] = "cancelled"
                            break
                        matrix._save_manifest()
                        continue
                    run.__exit__(None, None, None)
                    if run.status == "complete":
                        cell_entry["completed_run_ids"].append(run.id)
                    elif run.status == "cancelled":
                        cell_entry["cancelled_run_ids"].append(run.id)
                        cell_entry["status"] = "cancelled"
                        break
                    elif run.status == "failed":
                        cell_entry["failed_run_ids"].append(run.id)
                except PreflightCancel:
                    cell_entry["status"] = "cancelled"
                    if run is not None and run.id not in cell_entry["cancelled_run_ids"]:
                        cell_entry["cancelled_run_ids"].append(run.id)
                    break
                matrix._save_manifest()

            if cell_entry["status"] == "cancelled":
                return
            if len(cell_entry["completed_run_ids"]) >= matrix._repeats:
                cell_entry["status"] = "ok"
            elif len(cell_entry["failed_run_ids"]) >= matrix._max_failures:
                cell_entry["status"] = "failed"
            else:
                cell_entry["status"] = "partial"

        matrix._drive_cell = drive_with_handoff  # type: ignore[method-assign]
        matrix.execute(phase_runner)

    def _apply_handoff_to_matrix(self, mdata: dict[str, Any]) -> dict[str, Any]:
        """Merge cumulative handoff.params onto each cell params (handoff wins)."""
        import copy

        mdata = copy.deepcopy(mdata)
        handoff_params = dict(self._handoff.get("params") or {})
        if not handoff_params:
            return mdata
        msec = mdata.setdefault("matrix", {})
        cells = list(msec.get("cells") or [])
        for cell in cells:
            overlay = dict(cell.get("params") or {})
            overlay.update(handoff_params)
            cell["params"] = overlay
        msec["cells"] = cells
        return mdata

    def _materialized_handoff_artifacts(self) -> dict[str, Path]:
        out: dict[str, Path] = {}
        artifacts = dict(self._handoff.get("artifacts") or {})
        for stem, rel in artifacts.items():
            p = self.dir / rel
            if p.is_file():
                out[stem] = p
        return out

    def selectWinner(
        self,
        matrix: MatrixRun,
        phase_cfg: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Pick winner among ok cells. Returns winners.json phase entry or None."""
        force = phase_cfg.get("winner_cell", phase_cfg.get("force_cell"))
        metric = phase_cfg.get("winner_metric")
        direction = phase_cfg.get("winner_direction", "max")
        ok_cells = [c for c in matrix._manifest["cells"] if c["status"] == "ok"]
        if not ok_cells:
            return None

        stats_path = matrix.dir / "stats.json"
        stats = read_json(stats_path) if stats_path.is_file() else {"cells": {}}
        cells_stats = stats.get("cells") or {}

        if force is not None:
            if not any(c["id"] == force for c in ok_cells):
                return None
            value = None
            if metric and force in cells_stats:
                m = cells_stats[force].get(metric)
                if isinstance(m, dict):
                    value = m.get("mean")
            return {
                "cell_id": force,
                "metric": metric,
                "direction": direction,
                "value": value,
                "matrix_id": matrix.id,
            }

        if not metric:
            # first ok in config order
            cid = ok_cells[0]["id"]
            return {
                "cell_id": cid,
                "metric": metric,
                "direction": direction,
                "value": None,
                "matrix_id": matrix.id,
            }

        best_id = None
        best_val = None
        for c in ok_cells:
            cid = c["id"]
            entry = cells_stats.get(cid) or {}
            m = entry.get(metric)
            if not isinstance(m, dict) or "mean" not in m:
                continue
            val = m["mean"]
            if best_val is None:
                best_val = val
                best_id = cid
            elif direction == "min":
                if val < best_val:
                    best_val = val
                    best_id = cid
            else:
                if val > best_val:
                    best_val = val
                    best_id = cid

        if best_id is None:
            return None
        return {
            "cell_id": best_id,
            "metric": metric,
            "direction": direction,
            "value": best_val,
            "matrix_id": matrix.id,
        }

    def _merge_handoff(
        self,
        phase_entry: dict[str, Any],
        phase_cfg: dict[str, Any],
        matrix: MatrixRun,
        winner_cell_id: str,
    ) -> None:
        phase_id = phase_entry["id"]
        handoff_keys = list(phase_cfg.get("handoff_keys") or [])
        cell_cfg = matrix._cell_cfg(winner_cell_id)
        _, run_data, params, _ = matrix._cell_fingerprint(cell_cfg)

        phase_params: dict[str, Any] = {}
        for key in handoff_keys:
            if key in params:
                phase_params[key] = params[key]
                self._handoff.setdefault("params", {})[key] = params[key]

        phase_artifacts: dict[str, str] = {}
        # copy pins from first completed run that has them
        cell_entry = next(c for c in matrix._manifest["cells"] if c["id"] == winner_cell_id)
        for rid in cell_entry["completed_run_ids"]:
            try:
                rdir = self.ledger.run_dir(rid)
            except KeyError:
                rdir = self.ledger.results / "run" / rid
            if not rdir.is_dir():
                continue
            meta = read_metadata(rdir)
            pins = dict(meta.get("pins") or {})
            for stem, rel in pins.items():
                src = rdir / rel
                if not src.is_file():
                    continue
                rel_out = self.ledger.put_handoff_artifact(
                    self.id,
                    phase_id,
                    stem,
                    src.read_bytes(),
                    filename=str(src.name),
                )
                phase_artifacts[stem] = rel_out
                self._handoff.setdefault("artifacts", {})[stem] = rel_out

        self._handoff.setdefault("by_phase", {})[str(phase_id)] = {
            "params": phase_params,
            "artifacts": phase_artifacts,
        }
        self._save_handoff()

    @classmethod
    def resume(cls, dir: str | Path, *, ledger: Any | None = None) -> CampaignRun:
        d = Path(dir)
        meta = read_metadata(d)
        c = cls.__new__(cls)
        c.ledger = ledger or LocalFsLedger()
        c.ledger.register_campaign_dir(meta["id"], d)
        c._id = meta["id"]
        c._dir = d
        c._status = meta.get("status", "running")
        c._config_data = load_toml(d / "config.toml")
        c._config_stem = meta.get("config_stem") or d.name
        c._name = meta.get("name") or c._config_stem
        csec = dict(c._config_data.get("campaign") or {})
        c._repeats = csec.get("repeats")
        c._max_failures = csec.get("max_failures")
        c._continue_on_fail = bool(csec.get("continue_on_fail", False))
        c._phases_cfg = list(csec.get("phases") or [])
        c._phase_ids_filter = None
        c._manifest = read_manifest(d)
        handoff_path = d / "handoff.json"
        c._handoff = (
            read_json(handoff_path)
            if handoff_path.is_file()
            else {"params": {}, "artifacts": {}, "by_phase": {}}
        )
        winners_path = d / "winners.json"
        c._winners = read_json(winners_path) if winners_path.is_file() else {"phases": {}}
        c._resuming = True
        c._config_path = d / "config.toml"
        if c._status not in ("complete", "cancelled"):
            c._status = "running"
            meta["status"] = "running"
            write_metadata(d, meta)
        return c
