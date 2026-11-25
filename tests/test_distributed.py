"""Integration: store + matrix drive thread + worker_loop."""

from __future__ import annotations

import json
import socket
import threading
import time

import pytest
import uvicorn

from bench_run import Run
from bench_run.config import dump_toml
from bench_run.ledger.coordinator import CoordinatorLedger
from bench_run.layers.matrix import MatrixRun
from bench_run.execution.server.app import create_app
from bench_run.execution.server.store import ServerStore
from bench_run.execution.worker import worker_loop


@pytest.fixture(autouse=True)
def _bench_root(tmp_path, monkeypatch):
    monkeypatch.setenv("BENCH_RUN_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    for kind in ("run", "matrix", "campaign", "execution"):
        (tmp_path / "configs" / kind).mkdir(parents=True)
    return tmp_path


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_distributed_one_cell_matrix(tmp_path):
    dump_toml(
        {"run": {"name": "r1"}, "params": {"k": 1}},
        tmp_path / "configs" / "run" / "r1.toml",
    )

    store = ServerStore(tmp_path / "coord", lease_scan_s=60.0)
    app = create_app(store)
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    t_srv = threading.Thread(target=server.run, daemon=True)
    t_srv.start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "uvicorn failed to start"

    url = f"http://127.0.0.1:{port}"
    ledger = CoordinatorLedger(url)

    matrix_cfg = {
        "matrix": {
            "name": "m1",
            "repeats": 1,
            "cells": [{"id": "c1", "config": "r1.toml"}],
        }
    }
    matrix = MatrixRun(matrix_cfg, name="m1", ledger=store)

    done = threading.Event()
    err: list[BaseException] = []

    def drive() -> None:
        try:
            matrix.execute(None, distributed=True)
        except BaseException as exc:
            err.append(exc)
        finally:
            done.set()

    t_drive = threading.Thread(target=drive, daemon=True)
    t_drive.start()

    for _ in range(100):
        if store.queue.pending or store.queue.leases:
            break
        time.sleep(0.05)

    stop = threading.Event()

    def runner(run: Run) -> None:
        run.add_metric("accuracy", 0.77)

    def work() -> None:
        worker_loop(
            runner,
            ledger,
            worker_id="test-worker",
            poll_s=0.05,
            lease_s=60,
            stop_event=stop,
            max_claims=5,
            log_to_console=False,
        )

    t_worker = threading.Thread(target=work, daemon=True)
    t_worker.start()

    ok = done.wait(timeout=30)
    stop.set()
    t_worker.join(timeout=5)
    server.should_exit = True
    t_srv.join(timeout=5)
    store.close()
    ledger.close()

    assert ok, f"matrix drive timed out; err={err}; pending={len(store.queue.pending)} leases={list(store.queue.leases)}"
    if err:
        raise err[0]

    assert matrix.status == "complete"
    stats_path = matrix.dir / "stats.json"
    assert stats_path.is_file(), "stats.json missing"
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    assert "c1" in stats["cells"]
    assert stats["cells"]["c1"]["accuracy"]["mean"] == pytest.approx(0.77)
