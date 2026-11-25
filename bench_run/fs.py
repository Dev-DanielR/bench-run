"""Filesystem helpers: JSON IO, stamps, metadata/metrics/manifest."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=False, ensure_ascii=True)
        f.write("\n")


def allocate_stamp_dir(parent: Path, stem: str) -> tuple[str, Path]:
    """Create unique ``YYYYMMDD_HHMMSS_<stem>[_N]`` under parent. Returns (id, path)."""
    parent.mkdir(parents=True, exist_ok=True)
    base = f"{utc_stamp()}_{stem}"
    candidate = parent / base
    if not candidate.exists():
        candidate.mkdir(parents=True, exist_ok=False)
        return base, candidate
    n = 2
    while True:
        name = f"{base}_{n}"
        candidate = parent / name
        if not candidate.exists():
            candidate.mkdir(parents=True, exist_ok=False)
            return name, candidate
        n += 1


def write_metadata(dir_path: Path, metadata: dict[str, Any]) -> None:
    metadata = dict(metadata)
    metadata["updated_at"] = utc_now_iso()
    write_json(dir_path / "metadata.json", metadata)


def read_metadata(dir_path: Path) -> dict[str, Any]:
    return read_json(dir_path / "metadata.json")


def write_metrics(dir_path: Path, metrics: dict[str, Any]) -> None:
    write_json(dir_path / "metrics.json", metrics)


def read_metrics(dir_path: Path) -> dict[str, Any]:
    p = dir_path / "metrics.json"
    if not p.is_file():
        return {"run": {}, "items": {}}
    return read_json(p)


def write_manifest(dir_path: Path, manifest: dict[str, Any]) -> None:
    manifest = dict(manifest)
    manifest["updated_at"] = utc_now_iso()
    write_json(dir_path / "manifest.json", manifest)


def read_manifest(dir_path: Path) -> dict[str, Any]:
    return read_json(dir_path / "manifest.json")
