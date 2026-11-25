"""workspace_root discovery: env, .bench-run sidecar, cwd."""

from __future__ import annotations

from bench_run.config import SIDECAR_DIRNAME, bench_run_dir, workspace_root


def test_env_wins_over_sidecar(tmp_path, monkeypatch):
    sidecar = tmp_path / SIDECAR_DIRNAME
    sidecar.mkdir()
    explicit = tmp_path / "explicit"
    explicit.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BENCH_RUN_ROOT", str(explicit))
    assert workspace_root() == explicit.resolve()
    assert bench_run_dir() == explicit.resolve()


def test_sidecar_when_present(tmp_path, monkeypatch):
    sidecar = tmp_path / SIDECAR_DIRNAME
    sidecar.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BENCH_RUN_ROOT", raising=False)
    assert workspace_root() == sidecar.resolve()


def test_cwd_when_no_sidecar(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BENCH_RUN_ROOT", raising=False)
    assert workspace_root() == tmp_path.resolve()
    assert not (tmp_path / SIDECAR_DIRNAME).exists()
