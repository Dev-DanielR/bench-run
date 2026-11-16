"""Fingerprint golden vectors."""

from __future__ import annotations

import hashlib
import json

import pytest

from bench_run.fingerprint import FingerprintError, compute_fingerprint


def _manual(config_stem, params, fingerprint_fields):
    payload = {
        "config_stem": config_stem,
        "fingerprint_fields": fingerprint_fields,
        "params": params,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def test_sorted_keys_and_bool():
    params = {"z": 1, "a": True, "m": False}
    fp = compute_fingerprint("baseline", params, ["a", "z"])
    expected = _manual(
        "baseline",
        {"z": 1, "a": True, "m": False},
        {"a": True, "z": 1},
    )
    assert fp == expected
    assert fp.startswith("sha256:")


def test_missing_fingerprint_key_omitted():
    params = {"a": 1}
    fp = compute_fingerprint("x", params, ["a", "missing"])
    expected = _manual("x", {"a": 1}, {"a": 1})
    assert fp == expected


def test_empty_fingerprint_keys():
    params = {"a": 1}
    fp = compute_fingerprint("x", params, [])
    expected = _manual("x", {"a": 1}, {})
    assert fp == expected


def test_reject_nan():
    with pytest.raises(FingerprintError):
        compute_fingerprint("x", {"v": float("nan")})


def test_reject_inf():
    with pytest.raises(FingerprintError):
        compute_fingerprint("x", {"v": float("inf")})


def test_nested_sort():
    params = {"outer": {"b": 2, "a": 1}}
    fp = compute_fingerprint("n", params, None)
    # canonical sorts nested keys too via sort_keys=True
    expected = _manual("n", {"outer": {"b": 2, "a": 1}}, {})
    assert fp == expected
