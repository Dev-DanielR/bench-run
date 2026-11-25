"""TOML load, path resolve, classify experiment vs execution."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Config load / classification / resolution error."""


def workspace_root() -> Path:
    env = os.environ.get("BENCH_RUN_ROOT")
    if env:
        return Path(env).resolve()
    return Path.cwd().resolve()


def bench_run_dir() -> Path:
    return workspace_root() / "bench_run"


def load_toml(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    with p.open("rb") as f:
        return tomllib.load(f)


def _stem_name(name: str) -> str:
    n = name.strip()
    if n.lower().endswith(".toml"):
        n = n[:-5]
    return n


def _unique_stem_search(stem: str, *dirs: Path) -> Path:
    matches: list[Path] = []
    for d in dirs:
        if not d.is_dir():
            continue
        for candidate in (d / f"{stem}.toml", d / stem):
            if candidate.is_file():
                matches.append(candidate.resolve())
    # de-dupe
    uniq: list[Path] = []
    seen: set[Path] = set()
    for m in matches:
        if m not in seen:
            seen.add(m)
            uniq.append(m)
    if len(uniq) == 0:
        raise ConfigError(f"no config found for stem {stem!r}")
    if len(uniq) > 1:
        raise ConfigError(f"ambiguous stem {stem!r}: {[str(p) for p in uniq]}")
    return uniq[0]


def _resolve_under(name: str | Path, subdir: str) -> Path:
    root = bench_run_dir()
    p = Path(name)
    if p.is_absolute() or "/" in str(name).replace("\\", "/") or "\\" in str(name):
        # path-like
        if not p.is_absolute():
            p = (workspace_root() / p).resolve()
        else:
            p = p.resolve()
        if p.is_file():
            return p
        if p.suffix != ".toml":
            alt = p.with_suffix(".toml")
            if alt.is_file():
                return alt
        raise ConfigError(f"config not found: {name}")
    stem = _stem_name(str(name))
    return _unique_stem_search(stem, root / "configs" / subdir)


def resolve_config_path(name: str | Path) -> Path:
    """Bare stem → bench_run/configs/run/<stem>.toml."""
    return _resolve_under(name, "run")


def resolve_matrix_config_path(name: str | Path) -> Path:
    return _resolve_under(name, "matrix")


def resolve_campaign_config_path(name: str | Path) -> Path:
    return _resolve_under(name, "campaign")


def resolve_execution_config_path(name: str | Path) -> Path:
    return _resolve_under(name, "execution")


EXPERIMENT_KINDS = ("run", "matrix", "campaign")
EXECUTION_KIND = "execution"


def _path_kind_heuristic(path: Path) -> str | None:
    parts = [p.lower() for p in path.resolve().parts]
    # look for .../configs/{run|matrix|campaign|execution}/...
    try:
        idx = parts.index("configs")
    except ValueError:
        return None
    if idx + 1 >= len(parts):
        return None
    kind = parts[idx + 1]
    if kind in ("run", "matrix", "campaign", "execution"):
        return kind
    return None


def _section_kind(data: dict[str, Any]) -> str | None:
    has_run = "run" in data
    has_matrix = "matrix" in data
    has_campaign = "campaign" in data
    has_coord = "coordinator" in data
    has_worker = "worker" in data
    exp_count = sum([has_run, has_matrix, has_campaign])
    has_exec = has_coord or has_worker
    if exp_count and has_exec:
        raise ConfigError("config mixes experiment and execution sections")
    if exp_count > 1:
        raise ConfigError("config has multiple experiment section kinds")
    if exp_count == 0 and not has_exec:
        raise ConfigError("config has no recognized sections")
    if has_exec:
        return EXECUTION_KIND
    if has_run:
        return "run"
    if has_matrix:
        return "matrix"
    if has_campaign:
        return "campaign"
    return None


def classify_config(path: Path | str, data: dict[str, Any] | None = None) -> str:
    """Return 'run' | 'matrix' | 'campaign' | 'execution'."""
    p = Path(path)
    kind = _path_kind_heuristic(p)
    if kind is not None:
        return kind
    if data is None:
        data = load_toml(p)
    return _section_kind(data)  # type: ignore[return-value]


def resolve_config_for_local(name: str | Path) -> tuple[Path, str, dict[str, Any]]:
    """Resolve a local experiment config. Returns (path, kind, data)."""
    root = bench_run_dir()
    p = Path(name)
    path_str = str(name)

    if p.is_absolute() or "/" in path_str.replace("\\", "/") or "\\" in path_str:
        if not p.is_absolute():
            p = (workspace_root() / p).resolve()
        else:
            p = p.resolve()
        if not p.is_file() and p.suffix != ".toml":
            alt = p.with_suffix(".toml")
            if alt.is_file():
                p = alt
        if not p.is_file():
            raise ConfigError(f"config not found: {name}")
        data = load_toml(p)
        kind = classify_config(p, data)
        if kind == EXECUTION_KIND:
            raise ConfigError("local mode expects an experiment config, got execution")
        return p, kind, data

    stem = _stem_name(path_str)
    try:
        found = _unique_stem_search(
            stem,
            root / "configs" / "run",
            root / "configs" / "matrix",
            root / "configs" / "campaign",
        )
    except ConfigError:
        raise
    data = load_toml(found)
    kind = classify_config(found, data)
    return found, kind, data


def dump_toml(data: dict[str, Any], path: Path) -> None:
    import tomli_w

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        tomli_w.dump(data, f)


def config_stem_of(path: Path | str | None, data: dict[str, Any] | None = None) -> str:
    if path is not None:
        p = Path(path)
        return p.stem if p.suffix == ".toml" else p.name
    if data:
        for section in ("run", "matrix", "campaign"):
            if section in data and isinstance(data[section], dict):
                name = data[section].get("name")
                if name:
                    return str(name)
    return "unnamed"


def section_name(data: dict[str, Any], kind: str) -> str | None:
    sec = data.get(kind)
    if isinstance(sec, dict):
        n = sec.get("name")
        return str(n) if n is not None else None
    return None
