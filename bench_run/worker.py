"""Worker claim loop: claim RunSpec → preflight → runner → push package."""

from __future__ import annotations

import os
import socket
import threading
import time
import tomllib
from pathlib import Path
from typing import Any, Callable

from bench_run.artifacts import utc_now_iso, write_metadata, write_metrics
from bench_run.config import dump_toml, workspace_root
from bench_run.ledger.coordinator import CoordinatorLedger
from bench_run.ledger.base import RunSpec
from bench_run.run import PreflightCancel, Run


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _heartbeat_loop(
    ledger: CoordinatorLedger,
    claim_id: str,
    interval_s: float,
    stop: threading.Event,
) -> None:
    while not stop.wait(interval_s):
        try:
            ledger.heartbeat_claim(claim_id)
        except Exception:
            break


def materialize_handoff(
    ledger: CoordinatorLedger,
    spec: RunSpec,
    run_dir: Path,
) -> dict[str, Path]:
    out: dict[str, Path] = {}
    arts = spec.get("handoff_artifacts") or {}
    if not arts:
        return out
    handoff_dir = run_dir / "handoff"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    for stem, info in arts.items():
        if not isinstance(info, dict):
            continue
        rel = info.get("path") or ""
        src_name = Path(rel).name or stem
        dest = handoff_dir / src_name
        try:
            if rel.startswith("http://") or rel.startswith("https://"):
                import httpx

                r = httpx.get(rel, timeout=60)
                r.raise_for_status()
                dest.write_bytes(r.content)
            else:
                ledger.download_artifact(rel, dest)
        except Exception:
            # best-effort: try campaign-relative via artifacts API already
            continue
        out[stem] = dest
    return out


def build_run_from_spec(
    spec: RunSpec,
    ledger: CoordinatorLedger,
    *,
    log_to_console: bool = False,
) -> Run:
    """Create a Run bound to the claim's run_id and local working dir."""
    run_id = spec["run_id"]
    config_data: dict[str, Any]
    if spec.get("config_toml"):
        config_data = tomllib.loads(spec["config_toml"])
    elif spec.get("config_data"):
        config_data = dict(spec["config_data"])
    else:
        config_data = {
            "run": {"name": spec.get("config_stem") or "run"},
            "params": dict(spec.get("params") or {}),
        }
    # overlay params from spec
    params = dict(config_data.get("params") or {})
    params.update(spec.get("params") or {})
    config_data["params"] = params

    path = ledger.results / "run" / run_id
    path.mkdir(parents=True, exist_ok=True)
    ledger.register_run_dir(run_id, path)
    ledger._buf(run_id)

    dump_toml(config_data, path / "config.toml")
    now = utc_now_iso()
    write_metadata(
        path,
        {
            "id": run_id,
            "layer": "run",
            "status": "running",
            "config_stem": spec.get("config_stem"),
            "name": (config_data.get("run") or {}).get("name") or spec.get("config_stem"),
            "created_at": now,
            "updated_at": now,
            "finished_at": None,
            "paths": {"dir": str(path), "config": "config.toml", "log": "log.txt"},
            "fingerprint": spec.get("fingerprint"),
            "pins": {},
            "parent": spec.get("parent"),
            "claim_id": spec.get("claim_id"),
        },
    )
    write_metrics(path, {"run": {}, "items": {}})
    (path / "log.txt").touch()

    handoff_paths = materialize_handoff(ledger, spec, path)

    run = Run(
        config_data,
        name=(config_data.get("run") or {}).get("name") or spec.get("config_stem"),
        log_to_console=log_to_console,
        ledger=ledger,
        parent=spec.get("parent"),
        fingerprint=spec.get("fingerprint"),
        handoff_artifacts=handoff_paths or None,
    )
    run._id = run_id
    run._dir = path
    run._status = "running"
    run._entered = True
    run._log_fp = (path / "log.txt").open("a", encoding="utf-8")
    run.handoff_artifacts = handoff_paths
    return run


def execute_claimed_run(
    spec: RunSpec,
    runner: Callable[[Run], None],
    ledger: CoordinatorLedger,
    *,
    log_to_console: bool = False,
) -> str:
    """Run one claimed spec. Returns terminal status."""
    claim_id = spec.get("claim_id") or ""
    lease_s = int(spec.get("lease_s") or 300)
    stop = threading.Event()
    hb = None
    if claim_id:
        interval = max(lease_s / 3.0, 1.0)
        hb = threading.Thread(
            target=_heartbeat_loop,
            args=(ledger, claim_id, interval, stop),
            daemon=True,
        )
        hb.start()

    run = build_run_from_spec(spec, ledger, log_to_console=log_to_console)
    status = "failed"
    try:
        try:
            run.preflight()
        except PreflightCancel as exc:
            run._mark_cancelled(str(exc) or "preflight cancel")
            status = "cancelled"
            return status
        try:
            runner(run)
            if run.status == "running":
                run.complete()
            status = run.status
        except Exception as exc:
            run.fail(exc)
            status = "failed"
    finally:
        stop.set()
        run._close_log()
        if claim_id:
            try:
                ledger.release_claim(claim_id)
            except Exception:
                pass
    return status


def worker_loop(
    runner: Callable[[Run], None],
    ledger: CoordinatorLedger,
    *,
    worker_id: str | None = None,
    poll_s: float = 2.0,
    lease_s: int = 300,
    filters: dict | None = None,
    stop_event: threading.Event | None = None,
    max_claims: int | None = None,
    log_to_console: bool = False,
) -> int:
    """Claim until stop_event or max_claims. Returns number of claims executed."""
    wid = worker_id or default_worker_id()
    stop = stop_event or threading.Event()
    n = 0
    while not stop.is_set():
        if max_claims is not None and n >= max_claims:
            break
        try:
            spec = ledger.claim_run(worker_id=wid, lease_s=lease_s, filters=filters)
        except Exception:
            if stop.wait(poll_s):
                break
            continue
        if spec is None:
            if stop.wait(poll_s):
                break
            continue
        execute_claimed_run(spec, runner, ledger, log_to_console=log_to_console)
        n += 1
    return n
