"""CLI arity and local matrix smoke."""

from __future__ import annotations

import sys

import pytest

from bench_run import Run, main
from bench_run.config import dump_toml
from bench_run.extras import COORD_EXTRA_HINT


@pytest.fixture(autouse=True)
def _bench_root(tmp_path, monkeypatch):
    monkeypatch.setenv("BENCH_RUN_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    for kind in ("run", "matrix", "campaign", "execution"):
        (tmp_path / "configs" / kind).mkdir(parents=True)
    return tmp_path


def test_bad_arity_no_config():
    def runner(run: Run) -> None:
        pass

    assert main(runner, argv=[]) == 1


def test_bad_arity_two_configs(tmp_path):
    dump_toml(
        {"run": {"name": "a"}, "params": {}},
        tmp_path / "configs" / "run" / "a.toml",
    )
    dump_toml(
        {"run": {"name": "b"}, "params": {}},
        tmp_path / "configs" / "run" / "b.toml",
    )

    def runner(run: Run) -> None:
        pass

    assert main(runner, argv=["--config", "a.toml", "--config", "b.toml"]) == 1


def test_role_worker_requires_url(tmp_path):
    dump_toml(
        {"worker": {}},
        tmp_path / "configs" / "execution" / "lab.toml",
    )

    def runner(run: Run) -> None:
        pass

    assert main(runner, argv=["--role", "worker", "--config", "lab.toml"]) == 1


def test_role_coordinator_requires_bind(tmp_path):
    dump_toml(
        {"coordinator": {"name": "lab"}},
        tmp_path / "configs" / "execution" / "lab.toml",
    )

    def runner(run: Run) -> None:
        pass

    assert main(runner, argv=["--role", "coordinator", "--config", "lab.toml"]) == 1


def test_role_worker_missing_coord_extra(tmp_path, monkeypatch, capsys):
    dump_toml(
        {"worker": {"url": "http://127.0.0.1:9"}},
        tmp_path / "configs" / "execution" / "lab.toml",
    )

    def _missing():
        print(f"error: {COORD_EXTRA_HINT}\n(no httpx)", file=sys.stderr)
        return None

    import importlib

    main_mod = importlib.import_module("bench_run.main")
    monkeypatch.setattr(main_mod, "_load_worker", _missing)

    def runner(run: Run) -> None:
        pass

    assert main(runner, argv=["--role", "worker", "--config", "lab.toml"]) == 1
    assert "bench-run[coord]" in capsys.readouterr().err


def test_local_matrix_smoke(tmp_path):
    dump_toml(
        {"run": {"name": "r1"}, "params": {"k": 1}},
        tmp_path / "configs" / "run" / "r1.toml",
    )
    dump_toml(
        {
            "matrix": {
                "name": "m1",
                "repeats": 1,
                "cells": [{"id": "c1", "config": "r1.toml"}],
            }
        },
        tmp_path / "configs" / "matrix" / "m1.toml",
    )

    def runner(run: Run) -> None:
        run.add_metric("accuracy", 0.42)

    code = main(runner, argv=["--config", "m1.toml", "--no-console-log"])
    assert code == 0
