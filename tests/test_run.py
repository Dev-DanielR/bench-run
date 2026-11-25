"""Run happy path, preflight cancel, __exit__ finalize."""

from __future__ import annotations

import pytest

from bench_run import PreflightCancel, Run
from bench_run.fs import read_metadata, read_metrics


@pytest.fixture(autouse=True)
def _bench_root(tmp_path, monkeypatch):
    monkeypatch.setenv("BENCH_RUN_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "configs" / "run").mkdir(parents=True)
    return tmp_path


def test_run_happy_path(tmp_path):
    cfg = {
        "run": {"name": "baseline", "fingerprint_keys": ["seed"]},
        "params": {"seed": 1},
    }
    with Run(cfg) as run:
        run.preflight()
        run.add_metric("accuracy", 0.8)
        run.write_output("out.txt", "hello")
        run.pin_artifact("out", "output/out.txt")
    assert run.status == "complete"
    meta = read_metadata(run.dir)
    assert meta["status"] == "complete"
    assert meta["fingerprint"].startswith("sha256:")
    assert meta["pins"]["out"] == "output/out.txt"
    metrics = read_metrics(run.dir)
    assert metrics["run"]["accuracy"] == 0.8
    assert (run.dir / "output" / "out.txt").read_text() == "hello"
    assert (run.dir / "config.toml").is_file()


def test_preflight_cancel_hook(tmp_path):
    cfg = {"run": {"name": "c"}, "params": {}}

    def hook(run):
        return False

    with Run(cfg, preflight_hook=hook) as run:
        with pytest.raises(PreflightCancel):
            run.preflight()
    assert run.status == "cancelled"
    meta = read_metadata(run.dir)
    assert meta["status"] == "cancelled"


def test_preflight_cancel_exception(tmp_path):
    cfg = {"run": {"name": "c"}, "params": {}}

    def hook(run):
        raise PreflightCancel("nope")

    with Run(cfg, preflight_hook=hook) as run:
        with pytest.raises(PreflightCancel):
            run.preflight()
    assert run.status == "cancelled"


def test_exit_completes_if_still_running(tmp_path):
    cfg = {"run": {"name": "auto"}, "params": {}}
    with Run(cfg) as run:
        run.add_metric("x", 1)
    assert run.status == "complete"


def test_exit_fails_on_exception(tmp_path):
    cfg = {"run": {"name": "boom"}, "params": {}}
    with pytest.raises(RuntimeError):
        with Run(cfg) as run:
            run.preflight()
            raise RuntimeError("boom")
    assert run.status == "failed"


def test_data_root_missing_cancels(tmp_path):
    cfg = {
        "run": {"name": "d"},
        "data": {"root": "data/missing_dataset"},
        "params": {},
    }
    with Run(cfg) as run:
        with pytest.raises(PreflightCancel):
            run.preflight()
    assert run.status == "cancelled"
