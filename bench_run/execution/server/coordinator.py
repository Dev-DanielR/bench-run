"""Coordinator role: serve ledger HTTP API and optionally drive matrix/campaign."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Any, Callable

from bench_run.config import workspace_root
from bench_run.execution.local import layer_exit_code, make_local_sink
from bench_run.execution.server.app import create_app
from bench_run.execution.server.store import ServerStore
from bench_run.fs import read_metadata
from bench_run.layers.campaign import CampaignRun
from bench_run.layers.matrix import MatrixRun


def run_coordinator(
    execution_data: dict,
    runner: Callable,
    *,
    experiment: tuple[Path, str, dict] | None = None,
    resume: str | None = None,
    name: str | None = None,
    cell_ids: list[str] | None = None,
    phase_ids: list[str] | None = None,
    until_done: bool = False,
    log_to_console: bool = True,
    tty_bar: bool = True,
) -> int:
    """Validate coordinator config, serve store, optionally drive an experiment."""
    del runner  # coordinator does not call the experiment runner
    csec = dict(execution_data.get("coordinator") or {})
    bind = csec.get("bind")
    if not bind:
        print("error: coordinator.bind required", file=sys.stderr)
        return 1
    data_dir = csec.get("data_dir")
    if data_dir:
        data_dir = Path(data_dir)
        if not data_dir.is_absolute():
            data_dir = workspace_root() / data_dir
    else:
        data_dir = workspace_root() / "bench_run" / "results" / "_coordinator"
    auth = csec.get("auth") or {}
    token_env = auth.get("token_env")
    token = os.environ.get(token_env) if token_env else None
    lease_scan_s = float(csec.get("lease_scan_s") or 10.0)

    if until_done and experiment is None and not resume:
        print(
            "error: --until-done requires an experiment --config or --resume",
            file=sys.stderr,
        )
        return 1

    store = ServerStore(data_dir, lease_scan_s=lease_scan_s)
    app = create_app(store, token=token)

    drive_result: dict[str, Any] = {"code": 0, "error": None, "done": threading.Event()}

    def _finish_drive(code: int = 0, error: BaseException | None = None) -> None:
        drive_result["code"] = code
        drive_result["error"] = error
        drive_result["done"].set()

    if resume and experiment is None:

        def drive_resume() -> None:
            try:
                d = Path(resume)
                if not d.is_absolute():
                    d = workspace_root() / d
                meta = read_metadata(d)
                sink = make_local_sink(log_to_console=log_to_console, tty_bar=tty_bar)
                if meta.get("layer") == "matrix":
                    m = MatrixRun.resume(d, ledger=store, sink=sink)
                    m.execute(None, distributed=True)
                    _finish_drive(layer_exit_code(m))
                elif meta.get("layer") == "campaign":
                    c = CampaignRun.resume(d, ledger=store, sink=sink)
                    c.execute(None, distributed=True)
                    _finish_drive(layer_exit_code(c))
                else:
                    _finish_drive(1)
            except BaseException as exc:
                _finish_drive(4, exc)

        threading.Thread(target=drive_resume, daemon=True).start()
    elif experiment is not None:
        path, kind, data = experiment

        def drive_exp() -> None:
            try:
                sink = make_local_sink(log_to_console=log_to_console, tty_bar=tty_bar)
                if kind == "matrix":
                    m = MatrixRun(
                        data,
                        name=name,
                        cell_ids=cell_ids or None,
                        ledger=store,
                        sink=sink,
                    )
                    m.execute(None, distributed=True)
                    _finish_drive(layer_exit_code(m))
                elif kind == "campaign":
                    c = CampaignRun(
                        data,
                        name=name,
                        phase_ids=phase_ids or None,
                        ledger=store,
                        sink=sink,
                    )
                    c.execute(None, distributed=True)
                    _finish_drive(layer_exit_code(c))
                elif kind == "run":
                    _finish_drive(0)
                else:
                    _finish_drive(1)
            except BaseException as exc:
                _finish_drive(2, exc)

        threading.Thread(target=drive_exp, daemon=True).start()
    elif until_done:
        _finish_drive(0)

    host, _, port_s = bind.partition(":")
    port = int(port_s or "8000")
    try:
        import uvicorn

        config = uvicorn.Config(
            app, host=host or "0.0.0.0", port=port, log_level="info", workers=1
        )
        server = uvicorn.Server(config)

        if until_done:

            def _watch_done() -> None:
                drive_result["done"].wait()
                server.should_exit = True

            threading.Thread(target=_watch_done, daemon=True).start()

        server.run()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4
    finally:
        store.close()

    if until_done:
        if drive_result["error"] is not None:
            print(f"error: {drive_result['error']}", file=sys.stderr)
        return int(drive_result["code"])
    return 0
