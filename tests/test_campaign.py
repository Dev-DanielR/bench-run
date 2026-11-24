"""Campaign handoff params and pins."""

from __future__ import annotations

import pytest

from bench_run import CampaignRun, Run
from bench_run.artifacts import read_json
from bench_run.config import dump_toml


@pytest.fixture(autouse=True)
def _bench_root(tmp_path, monkeypatch):
    monkeypatch.setenv("BENCH_RUN_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    for kind in ("run", "matrix", "campaign"):
        (tmp_path / "bench_run" / "configs" / kind).mkdir(parents=True)
    return tmp_path


def _setup_configs(tmp_path):
    dump_toml(
        {
            "run": {"name": "cell_a", "fingerprint_keys": ["mode_a", "mode_b"]},
            "params": {"mode_a": "x", "mode_b": "keep"},
        },
        tmp_path / "bench_run" / "configs" / "run" / "cell_a.toml",
    )
    dump_toml(
        {
            "run": {"name": "cell_b", "fingerprint_keys": ["mode_a", "mode_b"]},
            "params": {"mode_a": "y", "mode_b": "keep"},
        },
        tmp_path / "bench_run" / "configs" / "run" / "cell_b.toml",
    )
    dump_toml(
        {
            "matrix": {
                "name": "stage1",
                "repeats": 1,
                "cells": [
                    {"id": "a", "config": "cell_a.toml", "params": {"mode_a": "x"}},
                    {"id": "b", "config": "cell_b.toml", "params": {"mode_a": "y"}},
                ],
            }
        },
        tmp_path / "bench_run" / "configs" / "matrix" / "stage1.toml",
    )
    dump_toml(
        {
            "matrix": {
                "name": "stage2",
                "repeats": 1,
                "cells": [
                    {"id": "a", "config": "cell_a.toml"},
                    {"id": "b", "config": "cell_b.toml"},
                ],
            }
        },
        tmp_path / "bench_run" / "configs" / "matrix" / "stage2.toml",
    )
    dump_toml(
        {
            "campaign": {
                "name": "phased",
                "repeats": 1,
                "continue_on_fail": False,
                "phases": [
                    {
                        "id": 1,
                        "name": "stage_a",
                        "matrix": "stage1.toml",
                        "winner_metric": "accuracy",
                        "winner_direction": "max",
                        "handoff_keys": ["mode_a"],
                    },
                    {
                        "id": 2,
                        "name": "stage_b",
                        "matrix": "stage2.toml",
                        "winner_metric": "accuracy",
                        "winner_direction": "max",
                        "handoff_keys": ["mode_a"],
                    },
                ],
            }
        },
        tmp_path / "bench_run" / "configs" / "campaign" / "phased.toml",
    )


def test_two_phase_handoff_params_and_pin(tmp_path):
    _setup_configs(tmp_path)
    seen_phase2_params = []

    def runner(run: Run) -> None:
        mode = run.params.get("mode_a")
        # phase1: a gets 0.9, b gets 0.5 → winner a, handoff mode_a=x
        score = 0.9 if mode == "x" else 0.5
        parent = run.parent or {}
        run.add_metric("accuracy", score)
        if str(parent.get("phase_id")) == "2":
            seen_phase2_params.append(dict(run.params))
        run.write_output("model.bin", b"weights")
        run.pin_artifact("model", "output/model.bin")

    campaign = CampaignRun("phased.toml")
    campaign.execute(runner)

    assert campaign.status == "complete"
    winners = read_json(campaign.dir / "winners.json")
    assert winners["phases"]["1"]["cell_id"] == "a"
    handoff = read_json(campaign.dir / "handoff.json")
    assert handoff["params"]["mode_a"] == "x"
    assert "model" in handoff["artifacts"]
    art_path = campaign.dir / handoff["artifacts"]["model"]
    assert art_path.is_file()
    assert art_path.read_bytes() == b"weights"

    # phase 2 cells should have seen handoff mode_a=x
    assert seen_phase2_params
    for p in seen_phase2_params:
        assert p.get("mode_a") == "x"


def test_preflight_cancel_halts_campaign(tmp_path):
    _setup_configs(tmp_path)

    def runner(run: Run) -> None:
        run.add_metric("accuracy", 0.1)

    def hook(run: Run):
        raise __import__("bench_run").PreflightCancel("stop")

    # Inject cancel via monkeypatch on first run preflight — simpler: custom runner path
    # Use Matrix cell that fails preflight by missing data.root
    dump_toml(
        {
            "run": {"name": "bad"},
            "data": {"root": "data/nope"},
            "params": {},
        },
        tmp_path / "bench_run" / "configs" / "run" / "cell_a.toml",
    )

    campaign = CampaignRun("phased.toml")
    campaign.execute(runner)
    assert campaign.status == "cancelled"
    phases = {str(p["id"]): p for p in campaign._manifest["phases"]}
    assert phases["1"]["status"] == "cancelled"
