"""Campaign phase 1 / cell b (examples 03 / 04)."""

from __future__ import annotations


def run(*, mode: str) -> tuple[float, bytes]:
    return 0.5, f"weights-phase1-{mode}".encode()
