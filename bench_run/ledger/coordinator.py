"""HTTP client Ledger for workers talking to the coordinator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from bench_run.fs import (
    allocate_stamp_dir,
    read_metadata,
    read_metrics,
    utc_now_iso,
    write_json,
    write_metadata,
    write_metrics,
)
from bench_run.config import bench_run_dir, dump_toml, workspace_root
from bench_run.ledger.base import RunHandle, RunPackage, RunRecord, RunSpec


class CoordinatorLedger:
    """Buffers local working-copy IO; terminal methods upload multipart packages."""

    distributed = False  # client side — MatrixRun should not treat as server store

    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        local_root: Path | None = None,
        timeout_s: float = 60.0,
        sink: Any | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.root = Path(local_root) if local_root else bench_run_dir()
        self.results = self.root / "results"
        self.sink = sink
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout_s)
        self._run_dirs: dict[str, Path] = {}
        self._buffers: dict[str, dict[str, Any]] = {}
        self._matrix_dirs: dict[str, Path] = {}
        self._campaign_dirs: dict[str, Path] = {}

    def close(self) -> None:
        self._client.close()

    def _headers(self) -> dict[str, str]:
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}

    def _rel(self, path: Path) -> str:
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
        d = self.results / "run" / run_id
        if d.is_dir():
            self._run_dirs[run_id] = d
            return d
        raise KeyError(f"unknown run_id: {run_id}")

    def allocate_run_dir(self, stem: str) -> tuple[str, Path]:
        rid, path = allocate_stamp_dir(self.results / "run", stem)
        self._run_dirs[rid] = path
        self._buffers[rid] = {"outputs": {}}
        return rid, path

    def _buf(self, run_id: str) -> dict[str, Any]:
        return self._buffers.setdefault(run_id, {"outputs": {}})

    def create_run(self, spec: RunSpec) -> RunHandle:
        stem = spec.get("name") or spec.get("config_stem") or "run"
        run_id = spec.get("run_id")
        if run_id:
            path = self.results / "run" / run_id
            path.mkdir(parents=True, exist_ok=True)
            self._run_dirs[run_id] = path
        else:
            run_id, path = self.allocate_run_dir(str(stem))
        self._buf(run_id)
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
            "paths": {"dir": self._rel(path), "config": "config.toml", "log": "log.txt"},
            "fingerprint": spec.get("fingerprint"),
            "pins": {},
            "parent": spec.get("parent"),
        }
        write_metadata(path, meta)
        if spec.get("config_data") is not None:
            dump_toml(spec["config_data"], path / "config.toml")
        elif spec.get("config_toml"):
            (path / "config.toml").write_text(spec["config_toml"], encoding="utf-8")
        (path / "log.txt").touch()
        write_metrics(path, {"run": {}, "items": {}})
        return {"run_id": run_id, "dir": str(path), "status": "running"}

    def put_output(self, run_id: str, relative_path: str, data: bytes) -> None:
        self._buf(run_id)["outputs"][relative_path] = data
        try:
            out = self.run_dir(run_id) / relative_path
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
        except Exception:
            pass

    def _build_package(self, run_id: str, status: str, *, error: str | None = None) -> RunPackage:
        buf = self._buf(run_id)
        path = self.run_dir(run_id)
        try:
            meta = read_metadata(path)
        except Exception:
            meta = {}
        pins = dict(meta.get("pins") or {})
        # also collect output/ files from disk
        outputs = dict(buf.get("outputs") or {})
        out_root = path / "output"
        if out_root.is_dir():
            for f in out_root.rglob("*"):
                if f.is_file():
                    rel = str(f.relative_to(path)).replace("\\", "/")
                    if rel not in outputs:
                        outputs[rel] = f.read_bytes()
        config_toml = ""
        cfg = path / "config.toml"
        if cfg.is_file():
            config_toml = cfg.read_text(encoding="utf-8")

        from bench_run.sink.base import Scope

        scope = Scope(layer="run", id=run_id, dir=path)
        log_text = ""
        metrics: dict[str, Any] = {"run": {}, "items": {}}
        if self.sink is not None:
            lt = self.sink.log_text(scope)
            if lt:
                log_text = lt
            ms = self.sink.metrics_snapshot(scope)
            if ms is not None:
                metrics = ms
        if not log_text:
            log_path = path / "log.txt"
            if log_path.is_file():
                log_text = log_path.read_text(encoding="utf-8")
        if metrics == {"run": {}, "items": {}}:
            try:
                metrics = read_metrics(path)
            except Exception:
                pass

        artifacts = [
            {"relative_path": rel, "data": data} for rel, data in outputs.items()
        ]
        return {
            "metadata": {
                "status": status,
                "fingerprint": meta.get("fingerprint"),
                "error": error,
                "pins": pins,
            },
            "metrics": metrics,
            "config_toml": config_toml,
            "log": log_text,
            "artifacts": artifacts,
        }

    def _put_package(self, run_id: str, package: RunPackage) -> None:
        files = []
        data = {
            "metadata": json.dumps(package.get("metadata") or {}),
            "metrics": json.dumps(package.get("metrics") or {}),
            "config_toml": package.get("config_toml") or "",
            "log": package.get("log") or "",
        }
        # httpx multipart: use files for artifacts + data fields
        multipart: list[tuple[str, Any]] = [
            ("metadata", (None, data["metadata"], "application/json")),
            ("metrics", (None, data["metrics"], "application/json")),
            ("config_toml", (None, data["config_toml"], "text/plain")),
            ("log", (None, data["log"], "text/plain")),
        ]
        for art in package.get("artifacts") or []:
            rel = art["relative_path"]
            raw = art["data"]
            multipart.append(
                ("artifact", (rel, raw, "application/octet-stream"))
            )
        r = self._client.put(
            f"/v1/runs/{run_id}/package",
            files=multipart,
            headers=self._headers(),
        )
        if r.status_code >= 400:
            raise RuntimeError(f"package upload failed: {r.status_code} {r.text}")

    def complete_run(self, run_id: str, package: RunPackage | None = None) -> None:
        pkg = package or self._build_package(run_id, "complete")
        meta = dict(pkg.get("metadata") or {})
        meta["status"] = "complete"
        pkg = dict(pkg)
        pkg["metadata"] = meta
        self._put_package(run_id, pkg)
        try:
            path = self.run_dir(run_id)
            m = read_metadata(path)
            m["status"] = "complete"
            m["finished_at"] = utc_now_iso()
            write_metadata(path, m)
        except Exception:
            pass

    def fail_run(self, run_id: str, error: str, package: RunPackage | None = None) -> None:
        pkg = package or self._build_package(run_id, "failed", error=error)
        meta = dict(pkg.get("metadata") or {})
        meta["status"] = "failed"
        meta["error"] = error
        pkg = dict(pkg)
        pkg["metadata"] = meta
        self._put_package(run_id, pkg)

    def cancel_run(self, run_id: str, reason: str = "") -> None:
        r = self._client.post(
            f"/v1/runs/{run_id}/cancel",
            json={"reason": reason},
            headers=self._headers(),
        )
        if r.status_code >= 400:
            # fallback package
            pkg = self._build_package(run_id, "cancelled", error=reason)
            try:
                self._put_package(run_id, pkg)
            except Exception:
                pass

    def get_run(self, run_id: str) -> RunRecord:
        r = self._client.get(f"/v1/runs/{run_id}", headers=self._headers())
        r.raise_for_status()
        return r.json()

    def find_completed_runs(self, fingerprint: str, *, limit: int) -> list[str]:
        r = self._client.get(
            f"/v1/fingerprints/{fingerprint}/runs",
            params={"limit": limit},
            headers=self._headers(),
        )
        r.raise_for_status()
        return list(r.json().get("run_ids") or [])

    def get_manifest(self, layer_id: str) -> dict:
        r = self._client.get(f"/v1/matrices/{layer_id}/manifest", headers=self._headers())
        if r.status_code == 404:
            r = self._client.get(
                f"/v1/campaigns/{layer_id}/manifest", headers=self._headers()
            )
        r.raise_for_status()
        return r.json()

    def put_manifest(self, layer_id: str, manifest: dict) -> None:
        raise NotImplementedError("workers do not put manifests")

    def put_matrix_stats(self, matrix_id: str, stats: dict) -> None:
        raise NotImplementedError

    def put_matrix_compare(self, matrix_id: str, compare: dict) -> None:
        raise NotImplementedError

    def put_matrix_figure(self, matrix_id: str, name: str, png: bytes) -> None:
        raise NotImplementedError

    def wait_matrix_terminal(self, matrix_id: str, *, timeout_s: float | None = None) -> dict:
        import time

        deadline = None if timeout_s is None else time.time() + timeout_s
        while True:
            manifest = self.get_manifest(matrix_id)
            cells = manifest.get("cells") or []
            if cells and all(
                c.get("status") in ("ok", "failed", "cancelled", "partial") for c in cells
            ):
                return manifest
            if deadline is not None and time.time() >= deadline:
                return manifest
            time.sleep(1.0)

    def put_campaign_manifest(self, campaign_id: str, manifest: dict) -> None:
        raise NotImplementedError

    def put_winners(self, campaign_id: str, winners: dict) -> None:
        raise NotImplementedError

    def put_handoff(self, campaign_id: str, handoff: dict) -> None:
        raise NotImplementedError

    def get_handoff(self, campaign_id: str) -> dict:
        r = self._client.get(
            f"/v1/campaigns/{campaign_id}/handoff", headers=self._headers()
        )
        r.raise_for_status()
        return r.json()

    def put_handoff_artifact(
        self,
        campaign_id: str,
        phase_id: str | int,
        stem: str,
        data: bytes,
        *,
        filename: str,
    ) -> str:
        raise NotImplementedError

    def enqueue_run(self, spec: RunSpec) -> None:
        raise NotImplementedError("workers do not enqueue")

    def claim_run(
        self,
        *,
        worker_id: str,
        lease_s: int = 300,
        filters: dict | None = None,
    ) -> RunSpec | None:
        body: dict[str, Any] = {"worker_id": worker_id, "lease_s": lease_s}
        if filters:
            body["filters"] = filters
        r = self._client.post("/v1/claims", json=body, headers=self._headers())
        if r.status_code == 204:
            return None
        r.raise_for_status()
        return r.json()

    def heartbeat_claim(self, claim_id: str) -> None:
        r = self._client.post(
            f"/v1/claims/{claim_id}/heartbeat", headers=self._headers()
        )
        if r.status_code == 410:
            raise RuntimeError("claim gone")
        r.raise_for_status()

    def release_claim(self, claim_id: str) -> None:
        self._client.delete(f"/v1/claims/{claim_id}", headers=self._headers())

    def download_artifact(self, rel_path: str, dest: Path) -> Path:
        r = self._client.get(f"/v1/artifacts/{rel_path}", headers=self._headers())
        r.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r.content)
        return dest
