"""Optional extras: figures hard-fail; core import without coord."""

from __future__ import annotations

import builtins
import sys

import pytest

from bench_run.extras import FIGURES_EXTRA_HINT
from bench_run.reporting.figures import write_matrix_figures


def test_import_core_without_loading_coord():
    """Fresh interpreter: core imports must not pull coord modules."""
    import subprocess

    script = """
import sys
import bench_run
from bench_run import Run, main
import bench_run.execution as execution
assert callable(main) and Run is not None
assert execution.local is not None
assert "bench_run.execution.worker" not in sys.modules
assert "bench_run.execution.server.coordinator" not in sys.modules
assert "bench_run.execution.server.app" not in sys.modules
print("ok")
"""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "ok" in proc.stdout


def test_figures_missing_matplotlib(tmp_path, monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "matplotlib" or name.startswith("matplotlib."):
            raise ImportError("matplotlib denied for test")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ImportError, match=r"bench-run\[figures\]") as ei:
        write_matrix_figures(
            tmp_path / "figures",
            {
                "metrics": ["accuracy"],
                "cells": {"c1": {"accuracy": {"mean": 0.5, "std": 0.0}}},
            },
        )
    assert FIGURES_EXTRA_HINT in str(ei.value)
