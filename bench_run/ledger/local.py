"""Local filesystem ledger under workspace/bench_run/results/."""

from __future__ import annotations

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
from bench_run.config import bench_run_dir, dump_toml, workspace_root
from bench_run.ledger.base import RunHandle, RunPackage, RunRecord, RunSpec


class LocalFsLedger:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else bench_run_dir()
        self.results = self.root / "results"
        self._run_dirs: dict[str, Path] = {}
        self._matrix_dirs: dict[str, Path] = {}
        self._campaign_dirs: dict[str, Path] = {}
        self._index_fingerprints()

    def _index_fingerprints(self) -> None:
        self._fp_index: dict[str, list[str]] = {}
        runs_root = self.results / "run"
        if not runs_root.is_dir():
            return
        for d in runs_root.iterdir():
            if not d.is_dir():
                continue
            meta_path = d / "metadata.json"
            if not meta_path.is_file():
                continue
            try:
                meta = read_json(meta_path)
            except Exception:
                continue
            if meta.get("status") != "complete":
                continue
            fp = meta.get("fingerprint")
            if not fp:
                continue
            self._fp_index.setdefault(fp, []).append(meta.get("id") or d.name)
            self._run_dirs[meta.get("id") or d.name] = d

    def _rel(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(workspace_root()))
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
        d = self.results / "run" / run_id
        if d.is_dir():
            self._run_dirs[run_id] = d
            return d
        raise KeyError(f"unknown run_id: {run_id}")

    def matrix_dir(self, matrix_id: str) -> Path:
        if matrix_id in self._matrix_dirs:
            return self._matrix_dirs[matrix_id]
        d = self.results / "matrix" / matrix_id
        if d.is_dir():
            self._matrix_dirs[matrix_id] = d
            return d
        raise KeyError(f"unknown matrix_id: {matrix_id}")

    def campaign_dir(self, campaign_id: str) -> Path:
        if campaign_id in self._campaign_dirs:
            return self._campaign_dirs[campaign_id]
        d = self.results / "campaign" / campaign_id
        if d.is_dir():
            self._campaign_dirs[campaign_id] = d
            return d
        raise KeyError(f"unknown campaign_id: {campaign_id}")

    def allocate_run_dir(self, stem: str) -> tuple[str, Path]:
        rid, path = allocate_stamp_dir(self.results / "run", stem)
        self._run_dirs[rid] = path
        return rid, path

    def allocate_matrix_dir(self, stem: str) -> tuple[str, Path]:
        mid, path = allocate_stamp_dir(self.results / "matrix", stem)
        self._matrix_dirs[mid] = path
        return mid, path

    def allocate_campaign_dir(self, stem: str) -> tuple[str, Path]:
        cid, path = allocate_stamp_dir(self.results / "campaign", stem)
        self._campaign_dirs[cid] = path
        return cid, path

    # --- Runs ---

    def create_run(self, spec: RunSpec) -> RunHandle:
        stem = spec.get("name") or spec.get("config_stem") or "run"
        run_id = spec.get("run_id")
        if run_id:
            path = self.results / "run" / run_id
            path.mkdir(parents=True, exist_ok=True)
            self._run_dirs[run_id] = path
        else:
            run_id, path = self.allocate_run_dir(str(stem))
        now = utc_now_iso()
        meta = {
            "id": run_id,
            "layer": "run",
            "status": "running",
            "config_stem": spec.get("config_stem") or stem,
            "name": stem,
            "created_at": now,
            "updated_at": now,
            "finished_at": None,
            "paths": {
                "dir": self._rel(path),
                "config": "config.toml",
                "log": "log.txt",
            },
            "fingerprint": spec.get("fingerprint"),
            "pins": {},
            "parent": spec.get("parent"),
        }
        write_metadata(path, meta)
        if "config_data" in spec and spec["config_data"] is not None:
            dump_toml(spec["config_data"], path / "config.toml")
        elif spec.get("config_toml"):
            (path / "config.toml").write_text(spec["config_toml"], encoding="utf-8")
        (path / "log.txt").touch()
        write_metrics(path, {"run": {}, "items": {}})
        return {"run_id": run_id, "dir": str(path), "status": "running"}

    def write_metrics(self, run_id: str, metrics: dict) -> None:
        write_metrics(self.run_dir(run_id), metrics)

    def append_log(self, run_id: str, text: str) -> None:
        path = self.run_dir(run_id) / "log.txt"
        with path.open("a", encoding="utf-8") as f:
            f.write(text)
            if not text.endswith("\n"):
                f.write("\n")

    def put_output(self, run_id: str, relative_path: str, data: bytes) -> None:
        out = self.run_dir(run_id) / relative_path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)

    def _finalize_run(self, run_id: str, status: str, *, error: str | None = None) -> None:
        path = self.run_dir(run_id)
        meta = read_metadata(path)
        meta["status"] = status
        meta["finished_at"] = utc_now_iso()
        meta["updated_at"] = meta["finished_at"]
        if error is not None:
            meta["error"] = error
        write_metadata(path, meta)
        if status == "complete":
            fp = meta.get("fingerprint")
            if fp:
                ids = self._fp_index.setdefault(fp, [])
                if run_id not in ids:
                    ids.append(run_id)

    def complete_run(self, run_id: str, package: RunPackage | None = None) -> None:
        if package and package.get("metrics") is not None:
            self.write_metrics(run_id, package["metrics"])
        self._finalize_run(run_id, "complete")

    def fail_run(self, run_id: str, error: str, package: RunPackage | None = None) -> None:
        if package and package.get("metrics") is not None:
            self.write_metrics(run_id, package["metrics"])
        self._finalize_run(run_id, "failed", error=error)

    def cancel_run(self, run_id: str, reason: str = "") -> None:
        self._finalize_run(run_id, "cancelled", error=reason or None)

    def get_run(self, run_id: str) -> RunRecord:
        path = self.run_dir(run_id)
        meta = read_metadata(path)
        return {
            "run_id": run_id,
            "status": meta.get("status", "unknown"),
            "fingerprint": meta.get("fingerprint"),
            "config_stem": meta.get("config_stem"),
            "params": {},
            "parent": meta.get("parent"),
            "claim_id": None,
            "lease_expires_at": None,
            "error": meta.get("error"),
            "created_at": meta.get("created_at", ""),
            "updated_at": meta.get("updated_at", ""),
            "finished_at": meta.get("finished_at"),
            "package_present": (path / "metrics.json").is_file(),
        }

    def find_completed_runs(self, fingerprint: str, *, limit: int) -> list[str]:
        # refresh from disk for safety
        self._index_fingerprints()
        ids = list(self._fp_index.get(fingerprint, []))
        return ids[:limit]

    # --- Matrix ---

    def get_manifest(self, layer_id: str) -> dict:
        for lookup in (self.matrix_dir, self.campaign_dir):
            try:
                d = lookup(layer_id)
                return read_manifest(d)
            except KeyError:
                continue
        # try path scan
        for layer in ("matrix", "campaign"):
            d = self.results / layer / layer_id
            if (d / "manifest.json").is_file():
                return read_manifest(d)
        raise KeyError(f"manifest not found: {layer_id}")

    def put_manifest(self, layer_id: str, manifest: dict) -> None:
        try:
            d = self.matrix_dir(layer_id)
        except KeyError:
            d = self.results / "matrix" / layer_id
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
        return self.get_manifest(matrix_id)

    # --- Campaign ---

    def put_campaign_manifest(self, campaign_id: str, manifest: dict) -> None:
        try:
            d = self.campaign_dir(campaign_id)
        except KeyError:
            d = self.results / "campaign" / campaign_id
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
        # preserve extension from filename
        src = Path(filename)
        out_name = stem if src.suffix == "" else f"{stem}{src.suffix}"
        # if stem already has extension matching, use as-is
        if Path(stem).suffix:
            out_name = stem
        elif src.name and src.suffix:
            # use stem + source extension
            out_name = f"{Path(stem).stem}{src.suffix}"
        dest_dir = d / "handoff" / str(phase_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / out_name
        dest.write_bytes(data)
        return f"handoff/{phase_id}/{out_name}"

    # --- Work queue (local: no-ops / NotImplemented for claim) ---

    def enqueue_run(self, spec: RunSpec) -> None:
        return None

    def claim_run(
        self,
        *,
        worker_id: str,
        lease_s: int = 300,
        filters: dict | None = None,
    ) -> RunSpec | None:
        return None

    def heartbeat_claim(self, claim_id: str) -> None:
        return None

    def release_claim(self, claim_id: str) -> None:
        return None
