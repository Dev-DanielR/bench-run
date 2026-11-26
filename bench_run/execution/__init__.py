"""Execution roles: local drive, worker claim loop, coordinator server.

``worker`` and ``run_coordinator`` need the ``coord`` extra (httpx, starlette,
uvicorn, python-multipart). Import them only when using distributed roles.
"""

from __future__ import annotations

import importlib
from typing import Any

from bench_run.execution import local

__all__ = ["local", "worker", "run_coordinator"]


def __getattr__(name: str) -> Any:
    if name == "worker":
        return importlib.import_module("bench_run.execution.worker")
    if name == "run_coordinator":
        mod = importlib.import_module("bench_run.execution.server.coordinator")
        return mod.run_coordinator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
