"""Campaign phase 2 / cell a (examples 03 / 04)."""

from __future__ import annotations

from project.data import check_handoff_model


def run(*, mode: str, prior: bytes) -> tuple[float, bytes]:
    prior = check_handoff_model(prior)
    base = 0.95 if mode == "x" else 0.55
    score = base + (0.01 if b"-x" in prior else 0.0)
    return score, prior + b"|weights-phase2"
