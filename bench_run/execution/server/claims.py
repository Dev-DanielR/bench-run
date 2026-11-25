"""Claim queue: enqueue, claim, heartbeat, release, lease expiry."""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bench_run.ledger.base import RunSpec


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso() -> str:
    return _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


@dataclass
class Lease:
    claim_id: str
    run_id: str
    worker_id: str
    lease_s: int
    expires_at: float  # epoch seconds
    spec: RunSpec


@dataclass
class ClaimQueue:
    """In-memory claim queue with optional FS persistence under queue/."""

    data_dir: Path
    lock: threading.RLock = field(default_factory=threading.RLock)
    pending: list[RunSpec] = field(default_factory=list)
    leases: dict[str, Lease] = field(default_factory=dict)  # claim_id → Lease
    by_run: dict[str, str] = field(default_factory=dict)  # run_id → claim_id

    def __post_init__(self) -> None:
        qdir = self.data_dir / "queue"
        qdir.mkdir(parents=True, exist_ok=True)
        self._pending_path = qdir / "pending.jsonl"
        self._leases_path = qdir / "leases.json"
        self._load()

    def _load(self) -> None:
        if self._pending_path.is_file():
            pending: list[RunSpec] = []
            for line in self._pending_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    pending.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            self.pending = pending
        if self._leases_path.is_file():
            try:
                raw = json.loads(self._leases_path.read_text(encoding="utf-8"))
            except Exception:
                raw = {}
            for cid, entry in (raw or {}).items():
                spec = entry.get("spec") or {}
                lease = Lease(
                    claim_id=cid,
                    run_id=entry["run_id"],
                    worker_id=entry.get("worker_id", ""),
                    lease_s=int(entry.get("lease_s", 300)),
                    expires_at=float(entry.get("expires_at", 0)),
                    spec=spec,
                )
                self.leases[cid] = lease
                self.by_run[lease.run_id] = cid

    def _persist(self) -> None:
        qdir = self.data_dir / "queue"
        qdir.mkdir(parents=True, exist_ok=True)
        with self._pending_path.open("w", encoding="utf-8") as f:
            for spec in self.pending:
                f.write(json.dumps(spec, ensure_ascii=True) + "\n")
        leases_out: dict[str, Any] = {}
        for cid, lease in self.leases.items():
            leases_out[cid] = {
                "run_id": lease.run_id,
                "worker_id": lease.worker_id,
                "lease_s": lease.lease_s,
                "expires_at": lease.expires_at,
                "spec": dict(lease.spec),
            }
        self._leases_path.write_text(
            json.dumps(leases_out, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

    def enqueue(self, spec: RunSpec) -> None:
        with self.lock:
            # avoid duplicate pending for same run_id
            rid = spec.get("run_id")
            if rid:
                self.pending = [s for s in self.pending if s.get("run_id") != rid]
                if rid in self.by_run:
                    # already leased — leave lease
                    self._persist()
                    return
            self.pending.append(dict(spec))
            self._persist()

    def _matches_filters(self, spec: RunSpec, filters: dict | None) -> bool:
        if not filters:
            return True
        parent = spec.get("parent") or {}
        matrix_ids = filters.get("matrix_ids") or []
        campaign_ids = filters.get("campaign_ids") or []
        config_stems = filters.get("config_stems") or []
        fp_prefixes = filters.get("fingerprint_prefixes") or []
        tags = filters.get("tags") or []
        if tags:
            return False  # v1: no tags attached
        if matrix_ids:
            if parent.get("layer") == "matrix":
                mid = parent.get("id")
            else:
                mid = parent.get("matrix_id")
            if not mid or mid not in matrix_ids:
                return False
        if campaign_ids:
            if parent.get("layer") == "campaign":
                cid = parent.get("id")
            else:
                cid = parent.get("campaign_id")
            if not cid or cid not in campaign_ids:
                return False
        if config_stems:
            stem = spec.get("config_stem")
            if stem not in config_stems:
                return False
        if fp_prefixes:
            fp = str(spec.get("fingerprint") or "")
            if not any(fp.startswith(p) for p in fp_prefixes):
                return False
        return True

    def claim(
        self,
        *,
        worker_id: str,
        lease_s: int = 300,
        filters: dict | None = None,
    ) -> RunSpec | None:
        with self.lock:
            self._expire_locked(time.time())
            for i, spec in enumerate(self.pending):
                if not self._matches_filters(spec, filters):
                    continue
                claim_id = uuid.uuid4().hex
                now = time.time()
                out = dict(spec)
                out["claim_id"] = claim_id
                out["lease_s"] = lease_s
                lease = Lease(
                    claim_id=claim_id,
                    run_id=str(out.get("run_id")),
                    worker_id=worker_id,
                    lease_s=lease_s,
                    expires_at=now + lease_s,
                    spec=out,
                )
                self.pending.pop(i)
                self.leases[claim_id] = lease
                self.by_run[lease.run_id] = claim_id
                self._persist()
                return out
            return None

    def heartbeat(self, claim_id: str) -> None:
        with self.lock:
            lease = self.leases.get(claim_id)
            if lease is None:
                raise KeyError(claim_id)
            if time.time() > lease.expires_at:
                raise KeyError(claim_id)
            lease.expires_at = time.time() + lease.lease_s
            self._persist()

    def release(self, claim_id: str, *, requeue: bool = True) -> RunSpec | None:
        with self.lock:
            lease = self.leases.pop(claim_id, None)
            if lease is None:
                return None
            self.by_run.pop(lease.run_id, None)
            spec = dict(lease.spec)
            spec.pop("claim_id", None)
            if requeue:
                self.pending.append(spec)
            self._persist()
            return spec

    def drop_claim(self, claim_id: str) -> None:
        """Remove lease without re-queue (run terminal)."""
        with self.lock:
            lease = self.leases.pop(claim_id, None)
            if lease is None:
                return
            self.by_run.pop(lease.run_id, None)
            self.pending = [s for s in self.pending if s.get("run_id") != lease.run_id]
            self._persist()

    def expire_once(self) -> list[RunSpec]:
        with self.lock:
            return self._expire_locked(time.time())

    def _expire_locked(self, now: float) -> list[RunSpec]:
        expired: list[RunSpec] = []
        dead = [cid for cid, lease in self.leases.items() if lease.expires_at <= now]
        for cid in dead:
            lease = self.leases.pop(cid)
            self.by_run.pop(lease.run_id, None)
            spec = dict(lease.spec)
            spec.pop("claim_id", None)
            self.pending.append(spec)
            expired.append(spec)
        if dead:
            self._persist()
        return expired

    def in_flight_for_cell(self, matrix_id: str, cell_id: str) -> int:
        with self.lock:
            n = 0
            for spec in self.pending:
                parent = spec.get("parent") or {}
                if parent.get("id") == matrix_id and parent.get("cell_id") == cell_id:
                    n += 1
            for lease in self.leases.values():
                parent = (lease.spec.get("parent") or {})
                if parent.get("id") == matrix_id and parent.get("cell_id") == cell_id:
                    n += 1
            return n

    def start_expiry_scanner(self, interval_s: float, on_expire=None) -> threading.Event:
        stop = threading.Event()

        def loop() -> None:
            while not stop.wait(interval_s):
                expired = self.expire_once()
                if on_expire and expired:
                    on_expire(expired)

        t = threading.Thread(target=loop, name="lease-scan", daemon=True)
        t.start()
        return stop
