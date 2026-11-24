"""ServerStore: Ledger protocol on coordinator data_dir."""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Any

from bench_run.artifacts import (
    allocate_stamp_dir,
    read_json,
    read_manifest,
    read_metadata,
    read_metrics,
    utc_now_iso,
    write_json,
    write_manifest,
    write_metadata,
    write_metrics,
)
from bench_run.config import dump_toml, workspace_root
from bench_run.ledger.base import RunHandle, RunPackage, RunRecord, RunSpec
from bench_run.server.aggregate import maybe_aggregate_matrix, refresh_cell_status
from bench_run.server.claims import ClaimQueue


def _fp_key(fingerprint: str) -> str:
    s = fingerprint
    if s.startswith("sha256:"):
        s = s[7:]
    return "".join(c if c.isalnum() else "_" for c in s)[:128] or "unknown"


class ServerStore:
    """Filesystem ledger under data_dir with claim queue and terminal events."""

    distributed = True

    def __init__(
        self,
        data_dir: Path | str | None = None,
        *,
        lease_scan_s: float = 10.0,
    ) -> None:
        if data_dir is None:
            data_dir = workspace_root() / "bench_run" / "results" / "_coordinator"
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.results = self.data_dir  # compat for matrix/campaign fallbacks
        self._lock = threading.RLock()
        self._run_dirs: dict[str, Path] = {}
        self._matrix_dirs: dict[str, Path] = {}
        self._campaign_dirs: dict[str, Path] = {}
        self._fp_index: dict[str, list[str]] = {}
        self._matrix_events: dict[str, threading.Event] = {}
        self._spec_templates: dict[str, dict[str, RunSpec]] = {}  # mid → cell_id → template
        self.queue = ClaimQueue(self.data_dir)
        self._lease_stop = self.queue.start_expiry_scanner(lease_scan_s)
        self._index_fingerprints()
        self._scan_dirs()

    def close(self) -> None:
        self._lease_stop.set()

    def _scan_dirs(self) -> None:
        for sub, mapping in (
            ("runs", self._run_dirs),
            ("matrices", self._matrix_dirs),
            ("campaigns", self._campaign_dirs),
        ):
            root = self.data_dir / sub
            if not root.is_dir():
                continue
            for d in root.iterdir():
                if d.is_dir():
                    mapping[d.name] = d

    def _index_fingerprints(self) -> None:
        self._fp_index = {}
        fp_root = self.data_dir / "fingerprints"
        if fp_root.is_dir():
            for d in fp_root.iterdir():
                runs_path = d / "runs.json"
                if runs_path.is_file():
                    try:
                        data = read_json(runs_path)
                        ids = list(data.get("run_ids") or data if isinstance(data, list) else [])
                        # recover fp from first run meta if possible
                        for rid in ids:
                            try:
                                meta = read_metadata(self.data_dir / "runs" / rid)
                                fp = meta.get("fingerprint")
                                if fp:
                                    self._fp_index.setdefault(fp, [])
                                    if rid not in self._fp_index[fp]:
                                        self._fp_index[fp].append(rid)
                            except Exception:
                                pass
                    except Exception:
                        continue
        runs_root = self.data_dir / "runs"
        if runs_root.is_dir():
            for d in runs_root.iterdir():
                if not d.is_dir():
                    continue
                try:
                    meta = read_metadata(d)
                except Exception:
                    continue
                if meta.get("status") != "complete":
                    continue
                fp = meta.get("fingerprint")
                rid = meta.get("id") or d.name
                self._run_dirs[rid] = d
                if fp:
                    ids = self._fp_index.setdefault(fp, [])
                    if rid not in ids:
                        ids.append(rid)

    def _persist_fp(self, fingerprint: str, run_ids: list[str]) -> None:
        key = _fp_key(fingerprint)
        d = self.data_dir / "fingerprints" / key
        d.mkdir(parents=True, exist_ok=True)
        write_json(d / "runs.json", {"fingerprint": fingerprint, "run_ids": run_ids})

    def _rel(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.data_dir.resolve())).replace("\\", "/")
        except ValueError:
            try:
                return str(path.resolve().relative_to(workspace_root())).replace("\\", "/")
            except ValueError:
                return str(path.resolve())

    def register_run_dir(self, run_id: str, dir_path: Path) -> None:
        self._run_dirs[run_id] = Path(dir_path)

    def register_matrix_dir(self, matrix_id: str, dir_path: Path) -> None:
        self._matrix_dirs[matrix_id] = Path(dir_path)

    def register_campaign_dir(self, campaign_id: str, dir_path: Path) -> None:
        self._campaign_dirs[campaign_id] = Path(dir_path)

    def run_dir(self, run_id: str) -> Path:
        if run_id in self._run_dirs:
            return self._run_dirs[run_id]
        d = self.data_dir / "runs" / run_id
        if d.is_dir():
            self._run_dirs[run_id] = d
            return d
        raise KeyError(f"unknown run_id: {run_id}")

    def matrix_dir(self, matrix_id: str) -> Path:
        if matrix_id in self._matrix_dirs:
            return self._matrix_dirs[matrix_id]
        d = self.data_dir / "matrices" / matrix_id
        if d.is_dir():
            self._matrix_dirs[matrix_id] = d
            return d
        raise KeyError(f"unknown matrix_id: {matrix_id}")

    def campaign_dir(self, campaign_id: str) -> Path:
        if campaign_id in self._campaign_dirs:
            return self._campaign_dirs[campaign_id]
        d = self.data_dir / "campaigns" / campaign_id
        if d.is_dir():
            self._campaign_dirs[campaign_id] = d
            return d
        raise KeyError(f"unknown campaign_id: {campaign_id}")

    def allocate_run_dir(self, stem: str) -> tuple[str, Path]:
        rid, path = allocate_stamp_dir(self.data_dir / "runs", stem)
        self._run_dirs[rid] = path
        return rid, path

    def allocate_matrix_dir(self, stem: str) -> tuple[str, Path]:
        mid, path = allocate_stamp_dir(self.data_dir / "matrices", stem)
        self._matrix_dirs[mid] = path
        return mid, path

    def allocate_campaign_dir(self, stem: str) -> tuple[str, Path]:
        cid, path = allocate_stamp_dir(self.data_dir / "campaigns", stem)
        self._campaign_dirs[cid] = path
        return cid, path

    def matrix_event(self, matrix_id: str) -> threading.Event:
        with self._lock:
            ev = self._matrix_events.get(matrix_id)
            if ev is None:
                ev = threading.Event()
                self._matrix_events[matrix_id] = ev
            return ev

    def signal_matrix_terminal(self, matrix_id: str) -> None:
        self.matrix_event(matrix_id).set()

    def remember_spec_template(self, matrix_id: str, cell_id: str, spec: RunSpec) -> None:
        tmpl = dict(spec)
        tmpl.pop("run_id", None)
        tmpl.pop("claim_id", None)
        self._spec_templates.setdefault(matrix_id, {})[cell_id] = tmpl

    # --- Runs ---

    def create_run(self, spec: RunSpec) -> RunHandle:
        stem = spec.get("name") or spec.get("config_stem") or "run"
        run_id = spec.get("run_id")
        if run_id:
            path = self.data_dir / "runs" / run_id
            path.mkdir(parents=True, exist_ok=True)
            self._run_dirs[run_id] = path
        else:
            run_id, path = self.allocate_run_dir(str(stem))
        now = utc_now_iso()
        meta = {
            "id": run_id,
            "layer": "run",
            "status": "queued",
            "config_stem": spec.get("config_stem") or stem,
            "name": stem,
            "created_at": now,
            "updated_at": now,
            "finished_at": None,
            "paths": {"dir": self._rel(path), "config": "config.toml", "log": "log.txt"},
            "fingerprint": spec.get("fingerprint"),
            "pins": {},
            "parent": spec.get("parent"),
            "params": spec.get("params") or {},
        }
        write_metadata(path, meta)
        if spec.get("config_data") is not None:
            dump_toml(spec["config_data"], path / "config.toml")
        elif spec.get("config_toml"):
            (path / "config.toml").write_text(spec["config_toml"], encoding="utf-8")
        (path / "log.txt").touch()
        write_metrics(path, {"run": {}, "items": {}})
        return {"run_id": run_id, "dir": str(path), "status": "queued"}

    def put_output(self, run_id: str, relative_path: str, data: bytes) -> None:
        out = self.run_dir(run_id) / relative_path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)

    def _apply_package_files(self, run_id: str, package: RunPackage) -> None:
        path = self.run_dir(run_id)
        if package.get("metrics") is not None:
            write_metrics(path, package["metrics"])
        if package.get("config_toml"):
            (path / "config.toml").write_text(package["config_toml"], encoding="utf-8")
        if package.get("log") is not None:
            (path / "log.txt").write_text(package["log"], encoding="utf-8")
        for art in package.get("artifacts") or []:
            rel = art.get("relative_path") or art.get("filename")
            data = art.get("data")
            if rel is None or data is None:
                continue
            out = path / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(data, str):
                out.write_bytes(data.encode("utf-8"))
            else:
                out.write_bytes(data)

    def apply_terminal_package(
        self,
        run_id: str,
        status: str,
        package: RunPackage | None = None,
        *,
        error: str | None = None,
    ) -> RunRecord:
        """Store package, update parent matrix cell, maybe aggregate. Raises KeyError/Conflict."""
        with self._lock:
            path = self.run_dir(run_id)
            meta = read_metadata(path)
            cur = meta.get("status")
            terminal = ("complete", "failed", "cancelled")
            if cur in terminal:
                if cur == status:
                    return self.get_run(run_id)
                raise ConflictError(f"run {run_id} is {cur}, cannot set {status}")

            if package:
                self._apply_package_files(run_id, package)
                pins = (package.get("metadata") or {}).get("pins")
                if pins:
                    meta["pins"] = dict(pins)
                if package.get("metadata") and package["metadata"].get("fingerprint"):
                    meta["fingerprint"] = package["metadata"]["fingerprint"]

            now = utc_now_iso()
            meta["status"] = status
            meta["finished_at"] = now
            meta["updated_at"] = now
            if error is not None:
                meta["error"] = error
            elif package and (package.get("metadata") or {}).get("error"):
                meta["error"] = package["metadata"]["error"]
            write_metadata(path, meta)

            # drop claim
            claim_id = meta.get("claim_id") or (self.queue.by_run.get(run_id))
            if claim_id:
                self.queue.drop_claim(claim_id)
            meta["claim_id"] = None
            meta["lease_expires_at"] = None
            write_metadata(path, meta)

            if status == "complete":
                fp = meta.get("fingerprint")
                if fp:
                    ids = self._fp_index.setdefault(fp, [])
                    if run_id not in ids:
                        ids.append(run_id)
                    self._persist_fp(fp, ids)

            parent = meta.get("parent") or {}
            if parent.get("layer") == "matrix" and parent.get("id"):
                self._update_matrix_for_run(run_id, status, parent)

            return self.get_run(run_id)

    def _update_matrix_for_run(self, run_id: str, status: str, parent: dict) -> None:
        matrix_id = parent["id"]
        cell_id = parent.get("cell_id")
        try:
            manifest = self.get_manifest(matrix_id)
        except KeyError:
            return
        repeats = int(manifest.get("repeats") or 1)
        max_failures = int(manifest.get("max_failures") or repeats)
        for cell in manifest.get("cells") or []:
            if cell.get("id") != cell_id:
                continue
            for key in ("completed_run_ids", "failed_run_ids", "cancelled_run_ids"):
                cell.setdefault(key, [])
            # remove from other lists
            for key in ("completed_run_ids", "failed_run_ids", "cancelled_run_ids"):
                if run_id in cell[key]:
                    cell[key].remove(run_id)
            if status == "complete":
                cell["completed_run_ids"].append(run_id)
            elif status == "failed":
                cell["failed_run_ids"].append(run_id)
            elif status == "cancelled":
                cell["cancelled_run_ids"].append(run_id)
                cell["status"] = "cancelled"
            refresh_cell_status(cell, repeats=repeats, max_failures=max_failures)

            # replacement enqueue on failure
            if (
                status == "failed"
                and cell.get("status") not in ("ok", "failed", "cancelled")
                and len(cell["completed_run_ids"]) < repeats
                and len(cell["failed_run_ids"]) < max_failures
            ):
                in_flight = self.queue.in_flight_for_cell(matrix_id, cell_id)
                need = repeats - len(cell["completed_run_ids"]) - in_flight
                tmpl = (self._spec_templates.get(matrix_id) or {}).get(cell_id)
                if tmpl and need > 0:
                    for _ in range(need):
                        new_spec = dict(tmpl)
                        stem = new_spec.get("config_stem") or "run"
                        new_id, _ = self.allocate_run_dir(str(stem))
                        new_spec["run_id"] = new_id
                        parent2 = dict(new_spec.get("parent") or {})
                        parent2["repeat_index"] = (
                            len(cell["completed_run_ids"]) + len(cell["failed_run_ids"])
                        )
                        new_spec["parent"] = parent2
                        self.create_run(new_spec)
                        self.enqueue_run(new_spec)

            break
        self.put_manifest(matrix_id, manifest)
        maybe_aggregate_matrix(self, matrix_id)

    def complete_run(self, run_id: str, package: RunPackage | None = None) -> None:
        pkg = package or {"metadata": {"status": "complete"}, "metrics": {}}
        meta = dict(pkg.get("metadata") or {})
        meta["status"] = "complete"
        pkg = dict(pkg)
        pkg["metadata"] = meta
        self.apply_terminal_package(run_id, "complete", pkg)

    def fail_run(self, run_id: str, error: str, package: RunPackage | None = None) -> None:
        pkg = package or {"metadata": {"status": "failed", "error": error}, "metrics": {}}
        meta = dict(pkg.get("metadata") or {})
        meta["status"] = "failed"
        meta.setdefault("error", error)
        pkg = dict(pkg)
        pkg["metadata"] = meta
        self.apply_terminal_package(run_id, "failed", pkg, error=error)

    def cancel_run(self, run_id: str, reason: str = "") -> None:
        self.apply_terminal_package(
            run_id,
            "cancelled",
            {"metadata": {"status": "cancelled", "error": reason or None}, "metrics": {}},
            error=reason or None,
        )

    def get_run(self, run_id: str) -> RunRecord:
        path = self.run_dir(run_id)
        meta = read_metadata(path)
        claim_id = meta.get("claim_id")
        lease_exp = meta.get("lease_expires_at")
        if run_id in self.queue.by_run:
            cid = self.queue.by_run[run_id]
            lease = self.queue.leases.get(cid)
            if lease:
                claim_id = cid
                from datetime import datetime, timezone

                lease_exp = datetime.fromtimestamp(lease.expires_at, tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
        return {
            "run_id": run_id,
            "status": meta.get("status", "unknown"),
            "fingerprint": meta.get("fingerprint"),
            "config_stem": meta.get("config_stem"),
            "params": meta.get("params") or {},
            "parent": meta.get("parent"),
            "claim_id": claim_id,
            "lease_expires_at": lease_exp,
            "error": meta.get("error"),
            "created_at": meta.get("created_at", ""),
            "updated_at": meta.get("updated_at", ""),
            "finished_at": meta.get("finished_at"),
            "package_present": (path / "metrics.json").is_file()
            and meta.get("status") in ("complete", "failed", "cancelled"),
        }

    def find_completed_runs(self, fingerprint: str, *, limit: int) -> list[str]:
        self._index_fingerprints()
        return list(self._fp_index.get(fingerprint, []))[:limit]

    # --- Matrix / campaign ---

    def get_manifest(self, layer_id: str) -> dict:
        for lookup in (self.matrix_dir, self.campaign_dir):
            try:
                return read_manifest(lookup(layer_id))
            except KeyError:
                continue
        for sub in ("matrices", "campaigns"):
            d = self.data_dir / sub / layer_id
            if (d / "manifest.json").is_file():
                return read_manifest(d)
        raise KeyError(f"manifest not found: {layer_id}")

    def put_manifest(self, layer_id: str, manifest: dict) -> None:
        try:
            d = self.matrix_dir(layer_id)
        except KeyError:
            d = self.data_dir / "matrices" / layer_id
            d.mkdir(parents=True, exist_ok=True)
            self._matrix_dirs[layer_id] = d
        write_manifest(d, manifest)

    def put_matrix_stats(self, matrix_id: str, stats: dict) -> None:
        write_json(self.matrix_dir(matrix_id) / "stats.json", stats)

    def put_matrix_compare(self, matrix_id: str, compare: dict) -> None:
        write_json(self.matrix_dir(matrix_id) / "compare.json", compare)

    def put_matrix_figure(self, matrix_id: str, name: str, png: bytes) -> None:
        fig_dir = self.matrix_dir(matrix_id) / "figures"
        fig_dir.mkdir(parents=True, exist_ok=True)
        fname = name if name.endswith(".png") else f"{name}.png"
        (fig_dir / fname).write_bytes(png)

    def wait_matrix_terminal(self, matrix_id: str, *, timeout_s: float | None = None) -> dict:
        from bench_run.server.aggregate import matrix_all_terminal

        try:
            manifest = self.get_manifest(matrix_id)
            if matrix_all_terminal(manifest):
                maybe_aggregate_matrix(self, matrix_id)
                return self.get_manifest(matrix_id)
        except KeyError:
            pass
        ev = self.matrix_event(matrix_id)
        if timeout_s is None:
            ev.wait()
        else:
            ev.wait(timeout_s)
        return self.get_manifest(matrix_id)

    def put_campaign_manifest(self, campaign_id: str, manifest: dict) -> None:
        try:
            d = self.campaign_dir(campaign_id)
        except KeyError:
            d = self.data_dir / "campaigns" / campaign_id
            d.mkdir(parents=True, exist_ok=True)
            self._campaign_dirs[campaign_id] = d
        write_manifest(d, manifest)

    def put_winners(self, campaign_id: str, winners: dict) -> None:
        write_json(self.campaign_dir(campaign_id) / "winners.json", winners)

    def put_handoff(self, campaign_id: str, handoff: dict) -> None:
        write_json(self.campaign_dir(campaign_id) / "handoff.json", handoff)

    def get_handoff(self, campaign_id: str) -> dict:
        path = self.campaign_dir(campaign_id) / "handoff.json"
        if not path.is_file():
            return {"params": {}, "artifacts": {}, "by_phase": {}}
        return read_json(path)

    def put_handoff_artifact(
        self,
        campaign_id: str,
        phase_id: str | int,
        stem: str,
        data: bytes,
        *,
        filename: str,
    ) -> str:
        d = self.campaign_dir(campaign_id)
        src = Path(filename)
        out_name = stem if src.suffix == "" else f"{stem}{src.suffix}"
        if Path(stem).suffix:
            out_name = stem
        elif src.name and src.suffix:
            out_name = f"{Path(stem).stem}{src.suffix}"
        dest_dir = d / "handoff" / str(phase_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / out_name
        dest.write_bytes(data)
        return f"handoff/{phase_id}/{out_name}"

    # --- Claims ---

    def enqueue_run(self, spec: RunSpec) -> None:
        spec = dict(spec)
        if not spec.get("run_id"):
            stem = spec.get("name") or spec.get("config_stem") or "run"
            rid, _ = self.allocate_run_dir(str(stem))
            spec["run_id"] = rid
            self.create_run(spec)
        else:
            rid = spec["run_id"]
            try:
                self.run_dir(rid)
            except KeyError:
                self.create_run(spec)
            else:
                # ensure queued status if new
                path = self.run_dir(rid)
                if not (path / "metadata.json").is_file():
                    self.create_run(spec)
        parent = spec.get("parent") or {}
        if parent.get("layer") == "matrix" and parent.get("id") and parent.get("cell_id"):
            self.remember_spec_template(parent["id"], parent["cell_id"], spec)
        # mark running/queued
        try:
            path = self.run_dir(spec["run_id"])
            meta = read_metadata(path)
            if meta.get("status") not in ("complete", "failed", "cancelled"):
                meta["status"] = "queued"
                write_metadata(path, meta)
        except Exception:
            pass
        self.queue.enqueue(spec)

    def claim_run(
        self,
        *,
        worker_id: str,
        lease_s: int = 300,
        filters: dict | None = None,
    ) -> RunSpec | None:
        spec = self.queue.claim(worker_id=worker_id, lease_s=lease_s, filters=filters)
        if spec is None:
            return None
        rid = spec.get("run_id")
        if rid:
            try:
                path = self.run_dir(rid)
                meta = read_metadata(path)
                meta["status"] = "running"
                meta["claim_id"] = spec.get("claim_id")
                meta["updated_at"] = utc_now_iso()
                write_metadata(path, meta)
            except Exception:
                pass
        return spec

    def heartbeat_claim(self, claim_id: str) -> None:
        self.queue.heartbeat(claim_id)

    def release_claim(self, claim_id: str) -> None:
        spec = self.queue.release(claim_id, requeue=True)
        if spec and spec.get("run_id"):
            try:
                path = self.run_dir(spec["run_id"])
                meta = read_metadata(path)
                if meta.get("status") not in ("complete", "failed", "cancelled"):
                    meta["status"] = "queued"
                    meta["claim_id"] = None
                    write_metadata(path, meta)
            except Exception:
                pass

    def resolve_artifact_path(self, rel: str) -> Path:
        p = Path(rel)
        if p.is_absolute():
            return p
        return self.data_dir / rel


class ConflictError(Exception):
    pass
