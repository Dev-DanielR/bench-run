"""Execution roles: local drive, worker claim loop, coordinator server."""

from bench_run.execution import local, worker
from bench_run.execution.server.coordinator import run_coordinator

__all__ = ["local", "worker", "run_coordinator"]
