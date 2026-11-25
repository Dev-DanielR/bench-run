"""Progress log lines and --until-done CLI behavior."""

from __future__ import annotations

import socket
import threading
import time

import pytest
import uvicorn

from bench_run import Run, main
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
        (tmp_path / "bench_run" / "configs" / kind).mkdir(parents=True)
    return tmp_path


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_progress_matrix_lines(tmp_path):
    dump_toml(
        {"run": {"name": "r1"}, "params": {"k": 1}},
        tmp_path / "bench_run" / "configs" / "run" / "r1.toml",
    )
    dump_toml(
        {
            "matrix": {
                "name": "m1",
                "repeats": 1,
                "cells": [{"id": "c1", "config": "r1.toml"}],
            }
        },
        tmp_path / "bench_run" / "configs" / "matrix" / "m1.toml",
    )

    def runner(run: Run) -> None:
        run.add_metric("accuracy", 0.5)

    matrix = MatrixRun(
        "m1.toml",
        log_to_console=False,
        tty_bar=False,
    )
    matrix.execute(runner)
    log = (matrix.dir / "log.txt").read_text(encoding="utf-8")
    assert "matrix start" in log
    assert "cell=c1" in log
    assert "matrix complete" in log


def test_run_log_lines_not_doubled(tmp_path):
    dump_toml(
        {"run": {"name": "r1"}, "params": {}},
        tmp_path / "bench_run" / "configs" / "run" / "r1.toml",
    )

    def runner(run: Run) -> None:
        run.write_to_log("hello once")
        run.add_metric("x", 1)

    with Run("r1.toml", log_to_console=False, tty_bar=False) as run:
        run.preflight()
        runner(run)

    lines = [
        ln
        for ln in (run.dir / "log.txt").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    bodies = [ln.split(" ", 1)[1] for ln in lines]
    assert bodies.count("hello once") == 1
    assert bodies.count("complete") == 1
    assert len(bodies) == len(set(bodies))


def test_until_done_coord_requires_exp(tmp_path):
    dump_toml(
        {"coordinator": {"name": "lab", "bind": "127.0.0.1:0"}, "worker": {"url": "http://x"}},
        tmp_path / "bench_run" / "configs" / "execution" / "lab.toml",
    )

    def runner(run: Run) -> None:
        pass

    assert (
        main(
            runner,
            argv=["--role", "coordinator", "--config", "lab.toml", "--until-done"],
        )
        == 1
    )


def test_until_done_worker_idle(tmp_path):
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
    assert server.started

    url = f"http://127.0.0.1:{port}"
    ledger = CoordinatorLedger(url)

    def runner(run: Run) -> None:
        pass

    code = worker_loop(
        runner,
        ledger,
        poll_s=0.05,
        lease_s=30,
        until_done=True,
        idle_polls=3,
        health_url=url + "/health",
        log_to_console=False,
    )
    assert code == 0
    server.should_exit = True
    ledger.close()
    store.close()


def test_until_done_worker_coord_down(tmp_path):
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    ledger = CoordinatorLedger(url)

    def runner(run: Run) -> None:
        pass

    code = worker_loop(
        runner,
        ledger,
        poll_s=0.05,
        lease_s=30,
        until_done=True,
        idle_polls=2,
        health_url=url + "/health",
        log_to_console=False,
    )
    assert code == 4
    ledger.close()


def test_until_done_coordinator(tmp_path):
    dump_toml(
        {"run": {"name": "r1"}, "params": {}},
        tmp_path / "bench_run" / "configs" / "run" / "r1.toml",
    )
    dump_toml(
        {
            "matrix": {
                "name": "m1",
                "repeats": 1,
                "cells": [{"id": "c1", "config": "r1.toml"}],
            }
        },
        tmp_path / "bench_run" / "configs" / "matrix" / "m1.toml",
    )
    port = _free_port()
    dump_toml(
        {
            "coordinator": {"name": "lab", "bind": f"127.0.0.1:{port}"},
            "worker": {
                "url": f"http://127.0.0.1:{port}",
                "claim": {"poll_s": 0.1, "lease_s": 60},
            },
        },
        tmp_path / "bench_run" / "configs" / "execution" / "lab.toml",
    )

    def runner(run: Run) -> None:
        run.add_metric("accuracy", 0.9)

    coord_code: list[int] = []
    worker_code: list[int] = []

    def run_coord() -> None:
        coord_code.append(
            main(
                runner,
                argv=[
                    "--role",
                    "coordinator",
                    "--config",
                    "lab.toml",
                    "--config",
                    "m1.toml",
                    "--until-done",
                    "--no-progress",
                    "--no-console-log",
                ],
            )
        )

    def run_worker() -> None:
        # wait for health
        import httpx

        for _ in range(100):
            try:
                if httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.2).status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.05)
        worker_code.append(
            main(
                runner,
                argv=[
                    "--role",
                    "worker",
                    "--config",
                    "lab.toml",
                    "--until-done",
                    "--idle-polls",
                    "5",
                    "--no-console-log",
                ],
            )
        )

    t_c = threading.Thread(target=run_coord, daemon=True)
    t_w = threading.Thread(target=run_worker, daemon=True)
    t_c.start()
    t_w.start()
    t_c.join(timeout=30)
    t_w.join(timeout=30)
    assert coord_code == [0], coord_code
    assert worker_code == [0], worker_code
