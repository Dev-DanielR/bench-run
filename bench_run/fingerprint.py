"""Canonical fingerprint: sha256 of sorted JSON payload."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any


class FingerprintError(ValueError):
    """Raised when fingerprint payload contains non-JSON or non-finite floats."""


def _reject_nonfinite(obj: Any, path: str = "") -> Any:
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            raise FingerprintError(f"non-finite float at {path or 'root'}: {obj!r}")
        return obj
    if isinstance(obj, dict):
        return {k: _reject_nonfinite(v, f"{path}.{k}" if path else k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_reject_nonfinite(v, f"{path}[{i}]") for i, v in enumerate(obj)]
    return obj


def _fingerprint_fields(params: dict[str, Any], fingerprint_keys: list[str] | None) -> dict[str, Any]:
    if not fingerprint_keys:
        return {}
    out: dict[str, Any] = {}
    for key in fingerprint_keys:
        if key in params:
            out[key] = params[key]
    return out


def compute_fingerprint(
    config_stem: str,
    params: dict[str, Any] | None,
    fingerprint_keys: list[str] | None = None,
) -> str:
    """Return ``sha256:<hex>`` for the canonical fingerprint payload."""
    params = dict(params or {})
    fields = _fingerprint_fields(params, fingerprint_keys)
    payload = {
        "config_stem": config_stem,
        "fingerprint_fields": fields,
        "params": params,
    }
    payload = _reject_nonfinite(payload)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
