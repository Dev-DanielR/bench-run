"""Execution roles: local drive, worker claim loop, coordinator server.

``worker`` and ``run_coordinator`` need the ``coord`` extra (httpx, starlette,
uvicorn, python-multipart). Import them only when using distributed roles.
"""

from __future__ import annotations

from typing import Any

from bench_run.execution import local

__all__ = ["local", "worker", "run_coordinator"]


def __getattr__(name: str) -> Any:
    if name == "worker":
        from bench_run.execution import worker

        return worker
    if name == "run_coordinator":
        from bench_run.execution.server.coordinator import run_coordinator

        return run_coordinator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
