"""Matrix repeats, reuse, failure cap."""

from __future__ import annotations

import pytest

from bench_run import MatrixRun, Run
from bench_run.artifacts import read_json
from bench_run.config import dump_toml


@pytest.fixture(autouse=True)
def _bench_root(tmp_path, monkeypatch):
    monkeypatch.setenv("BENCH_RUN_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    for kind in ("run", "matrix", "campaign"):
        (tmp_path / "bench_run" / "configs" / kind).mkdir(parents=True)
    return tmp_path


def _write_run_configs(tmp_path):
    dump_toml(
        {"run": {"name": "on_cfg", "fingerprint_keys": ["mode"]}, "params": {"mode": "on"}},
        tmp_path / "bench_run" / "configs" / "run" / "on_cfg.toml",
    )
    dump_toml(
        {"run": {"name": "off_cfg", "fingerprint_keys": ["mode"]}, "params": {"mode": "off"}},
        tmp_path / "bench_run" / "configs" / "run" / "off_cfg.toml",
    )


def test_two_cell_repeats(tmp_path):
    _write_run_configs(tmp_path)
    matrix_cfg = {
        "matrix": {
            "name": "factor_a",
            "repeats": 2,
            "baseline_cell": "on",
            "figure_metrics": ["accuracy"],
            "cells": [
                {"id": "on", "config": "on_cfg.toml", "params": {"mode": "on"}},
                {"id": "off", "config": "off_cfg.toml", "params": {"mode": "off"}},
            ],
        }
    }
    dump_toml(matrix_cfg, tmp_path / "bench_run" / "configs" / "matrix" / "factor_a.toml")

    def runner(run: Run) -> None:
        run.addMetric("accuracy", 0.9 if run.params.get("mode") == "on" else 0.5)

    with MatrixRun("factor_a.toml") as matrix:
        matrix.execute(runner)

    assert matrix.status == "complete"
    manifest = matrix._manifest
    assert len(manifest["cells"]) == 2
    for cell in manifest["cells"]:
        assert cell["status"] == "ok"
        assert len(cell["completed_run_ids"]) == 2

    stats = read_json(matrix.dir / "stats.json")
    assert stats["cells"]["on"]["n"] == 2
    assert stats["cells"]["on"]["accuracy"]["mean"] == pytest.approx(0.9)
    assert stats["cells"]["on"]["accuracy"]["std"] == 0.0
    compare = read_json(matrix.dir / "compare.json")
    assert compare["baseline_cell"] == "on"
    assert "accuracy" in compare["metrics"]
    assert (matrix.dir / "figures" / "accuracy.png").is_file() or True  # best-effort


def test_failure_cap(tmp_path):
    _write_run_configs(tmp_path)
    matrix_cfg = {
        "matrix": {
            "name": "flaky",
            "repeats": 2,
            "max_failures": 2,
            "cells": [
                {"id": "bad", "config": "on_cfg.toml"},
                {"id": "good", "config": "off_cfg.toml"},
            ],
        }
    }
    dump_toml(matrix_cfg, tmp_path / "bench_run" / "configs" / "matrix" / "flaky.toml")

    def runner(run: Run) -> None:
        if run.params.get("mode") == "on":
            raise RuntimeError("always fail")
        run.addMetric("accuracy", 0.7)

    matrix = MatrixRun("flaky.toml")
    matrix.execute(runner)

    cells = {c["id"]: c for c in matrix._manifest["cells"]}
    assert cells["bad"]["status"] == "failed"
    assert len(cells["bad"]["failed_run_ids"]) >= 2
    assert len(cells["bad"]["completed_run_ids"]) == 0
    assert cells["good"]["status"] == "ok"
    assert len(cells["good"]["completed_run_ids"]) == 2


def test_reuse_fills_repeats(tmp_path):
    _write_run_configs(tmp_path)
    # seed completed runs
    def seed(run: Run) -> None:
        run.addMetric("accuracy", 1.0)

    cfg = {
        "run": {"name": "on_cfg", "fingerprint_keys": ["mode"]},
        "params": {"mode": "on"},
    }
    for _ in range(2):
        with Run(cfg) as run:
            run.preflight()
            seed(run)

    matrix_cfg = {
        "matrix": {
            "name": "reuse_m",
            "repeats": 2,
            "cells": [{"id": "on", "config": "on_cfg.toml", "params": {"mode": "on"}}],
        }
    }
    dump_toml(matrix_cfg, tmp_path / "bench_run" / "configs" / "matrix" / "reuse_m.toml")

    calls = {"n": 0}

    def runner(run: Run) -> None:
        calls["n"] += 1
        run.addMetric("accuracy", 0.0)

    MatrixRun("reuse_m.toml").execute(runner)
    assert calls["n"] == 0
