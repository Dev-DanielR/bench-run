"""CLI arity and local matrix smoke."""

from __future__ import annotations

import pytest

from bench_run import Run, main
from bench_run.config import dump_toml


@pytest.fixture(autouse=True)
def _bench_root(tmp_path, monkeypatch):
    monkeypatch.setenv("BENCH_RUN_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    for kind in ("run", "matrix", "campaign", "execution"):
        (tmp_path / "bench_run" / "configs" / kind).mkdir(parents=True)
    return tmp_path


def test_bad_arity_no_config():
    def runner(run: Run) -> None:
        pass

    assert main(runner, argv=[]) == 1


def test_bad_arity_two_configs(tmp_path):
    dump_toml(
        {"run": {"name": "a"}, "params": {}},
        tmp_path / "bench_run" / "configs" / "run" / "a.toml",
    )
    dump_toml(
        {"run": {"name": "b"}, "params": {}},
        tmp_path / "bench_run" / "configs" / "run" / "b.toml",
    )

    def runner(run: Run) -> None:
        pass

    assert main(runner, argv=["--config", "a.toml", "--config", "b.toml"]) == 1


def test_role_worker_requires_url(tmp_path):
    dump_toml(
        {"worker": {}},
        tmp_path / "bench_run" / "configs" / "execution" / "lab.toml",
    )

    def runner(run: Run) -> None:
        pass

    assert main(runner, argv=["--role", "worker", "--config", "lab.toml"]) == 1


def test_role_coordinator_requires_bind(tmp_path):
    dump_toml(
        {"coordinator": {"name": "lab"}},
        tmp_path / "bench_run" / "configs" / "execution" / "lab.toml",
    )

    def runner(run: Run) -> None:
        pass

    assert main(runner, argv=["--role", "coordinator", "--config", "lab.toml"]) == 1


def test_local_matrix_smoke(tmp_path):
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
        run.addMetric("accuracy", 0.42)

    code = main(runner, argv=["--config", "m1.toml", "--no-console-log"])
    assert code == 0
