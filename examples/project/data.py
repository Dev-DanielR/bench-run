"""Shared helpers for example domain cells."""

from __future__ import annotations

HANDOFF_PREFIX = b"weights-phase1-"


def check_handoff_model(data: bytes) -> bytes:
    if not data.startswith(HANDOFF_PREFIX):
        raise RuntimeError(f"unexpected handoff model contents: {data!r}")
    return data
