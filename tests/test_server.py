"""ASGI tests for coordinator store + REST."""

from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from bench_run.fs import utc_now_iso, write_manifest, write_metadata
from bench_run.execution.server.app import create_app
from bench_run.execution.server.store import ServerStore


@pytest.fixture
def store(tmp_path):
    s = ServerStore(tmp_path / "coord", lease_scan_s=60.0)
    yield s
    s.close()


@pytest.fixture
def client(store):
    app = create_app(store)
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_claim_empty_204(client):
    r = client.post("/v1/claims", json={"worker_id": "w1", "lease_s": 60})
    assert r.status_code == 204


def test_enqueue_claim_package(store, client):
    spec = {
        "run_id": "run_test_1",
        "config_stem": "baseline",
        "config_toml": '[run]\nname = "baseline"\n[params]\nk = 1\n',
        "params": {"k": 1},
        "fingerprint": "sha256:abc",
        "handoff_artifacts": {},
        "parent": {
            "layer": "matrix",
            "id": "mat1",
            "cell_id": "c1",
            "repeat_index": 0,
        },
        "lease_s": 60,
    }
    mdir = store.data_dir / "matrices" / "mat1"
    mdir.mkdir(parents=True)
    store.register_matrix_dir("mat1", mdir)
    write_metadata(
        mdir,
        {
            "id": "mat1",
            "layer": "matrix",
            "status": "running",
            "created_at": utc_now_iso(),
            "updated_at": utc_now_iso(),
        },
    )
    manifest = {
        "matrix_id": "mat1",
        "repeats": 1,
        "max_failures": 1,
        "baseline_cell": "c1",
        "cells": [
            {
                "id": "c1",
                "config_stem": "baseline",
                "fingerprint": "sha256:abc",
                "status": "running",
                "target_repeats": 1,
                "completed_run_ids": [],
                "failed_run_ids": [],
                "cancelled_run_ids": [],
                "reused_run_ids": [],
            }
        ],
    }
    write_manifest(mdir, manifest)
    store.put_manifest("mat1", manifest)

    store.enqueue_run(spec)

    r = client.post("/v1/claims", json={"worker_id": "w1", "lease_s": 60})
    assert r.status_code == 200
    claimed = r.json()
    assert claimed["run_id"] == "run_test_1"
    assert claimed["claim_id"]

    files = {
        "metadata": (None, json.dumps({"status": "complete", "fingerprint": "sha256:abc"}), "application/json"),
        "metrics": (None, json.dumps({"run": {"accuracy": 0.9}, "items": {}}), "application/json"),
        "config_toml": (None, spec["config_toml"], "text/plain"),
        "log": (None, "ok\n", "text/plain"),
    }
    r = client.put("/v1/runs/run_test_1/package", files=files)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "complete"

    rec = store.get_run("run_test_1")
    assert rec["status"] == "complete"
    man = store.get_manifest("mat1")
    assert "run_test_1" in man["cells"][0]["completed_run_ids"]
    assert man["cells"][0]["status"] == "ok"
