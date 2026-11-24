"""Ledger Protocol and shared type aliases."""

from __future__ import annotations

from typing import Any, Protocol, TypedDict


class RunSpec(TypedDict, total=False):
    run_id: str
    claim_id: str
    config_stem: str
    config_toml: str
    params: dict[str, Any]
    fingerprint: str
    handoff_artifacts: dict[str, dict[str, str]]
    parent: dict[str, Any]
    lease_s: int
    config_data: dict[str, Any]
    name: str


class RunHandle(TypedDict, total=False):
    run_id: str
    dir: str
    status: str


class RunRecord(TypedDict, total=False):
    run_id: str
    status: str
    fingerprint: str
    config_stem: str
    params: dict[str, Any]
    parent: dict[str, Any]
    claim_id: str | None
    lease_expires_at: str | None
    error: str | None
    created_at: str
    updated_at: str
    finished_at: str | None
    package_present: bool


class RunPackage(TypedDict, total=False):
    metadata: dict[str, Any]
    metrics: dict[str, Any]
    config_toml: str
    log: str
    artifacts: list[dict[str, Any]]


class Ledger(Protocol):
    def create_run(self, spec: RunSpec) -> RunHandle: ...

    def put_output(self, run_id: str, relative_path: str, data: bytes) -> None: ...

    def complete_run(self, run_id: str, package: RunPackage | None = None) -> None: ...

    def fail_run(self, run_id: str, error: str, package: RunPackage | None = None) -> None: ...

    def cancel_run(self, run_id: str, reason: str = "") -> None: ...

    def get_run(self, run_id: str) -> RunRecord: ...

    def find_completed_runs(self, fingerprint: str, *, limit: int) -> list[str]: ...

    def get_manifest(self, layer_id: str) -> dict: ...

    def put_manifest(self, layer_id: str, manifest: dict) -> None: ...

    def put_matrix_stats(self, matrix_id: str, stats: dict) -> None: ...

    def put_matrix_compare(self, matrix_id: str, compare: dict) -> None: ...

    def put_matrix_figure(self, matrix_id: str, name: str, png: bytes) -> None: ...

    def wait_matrix_terminal(self, matrix_id: str, *, timeout_s: float | None = None) -> dict: ...

    def put_campaign_manifest(self, campaign_id: str, manifest: dict) -> None: ...

    def put_winners(self, campaign_id: str, winners: dict) -> None: ...

    def put_handoff(self, campaign_id: str, handoff: dict) -> None: ...

    def get_handoff(self, campaign_id: str) -> dict: ...

    def put_handoff_artifact(
        self,
        campaign_id: str,
        phase_id: str | int,
        stem: str,
        data: bytes,
        *,
        filename: str,
    ) -> str: ...

    def enqueue_run(self, spec: RunSpec) -> None: ...

    def claim_run(
        self,
        *,
        worker_id: str,
        lease_s: int = 300,
        filters: dict | None = None,
    ) -> RunSpec | None: ...

    def heartbeat_claim(self, claim_id: str) -> None: ...

    def release_claim(self, claim_id: str) -> None: ...
