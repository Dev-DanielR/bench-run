"""Intentional / gated runtime failure (examples 04, 06)."""

from __future__ import annotations


def run(*, fail: bool = True, mode: str = "z") -> tuple[float, bytes]:
    if fail:
        raise RuntimeError("boom: intentional runtime failure")
    return 0.4, f"weights-phase1-{mode}".encode()
