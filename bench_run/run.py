"""Run context manager: lifecycle, metrics, preflight, pins."""

from __future__ import annotations

import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from bench_run.artifacts import (
    read_metadata,
    utc_now_iso,
    write_metadata,
    write_metrics,
)
from bench_run.config import (
    load_toml,
    resolveConfigPath,
    section_name,
    workspace_root,
    dump_toml,
)
from bench_run.fingerprint import compute_fingerprint
from bench_run.ledger.local import LocalFsLedger
from bench_run.sink.base import LogLine, MetricSet, ProgressLine, Scope
from bench_run.sink.local import LocalFsSink


class PreflightCancel(Exception):
    """Cancel a run before the runner body; does not count as runtime failure."""


class Run:
    def __init__(
        self,
        config: str | Path | dict,
        *,
        name: str | None = None,
        log_to_console: bool = True,
        tty_bar: bool | None = None,
        ledger: Any | None = None,
        sink: Any | None = None,
        preflight_hook: Callable[[Run], bool | None] | None = None,
        parent: dict | None = None,
        params_overlay: dict | None = None,
        handoff_artifacts: dict[str, Path] | None = None,
        fingerprint: str | None = None,
    ) -> None:
        self._preflight_hook = preflight_hook
        self._parent = parent
        self._params_overlay = dict(params_overlay or {})
        self._handoff_artifacts_in = dict(handoff_artifacts or {})
        self._fingerprint_override = fingerprint
        self.ledger: LocalFsLedger = ledger or LocalFsLedger()
        self.sink = sink or LocalFsSink(
            log_to_console=log_to_console,
            tty_bar=tty_bar,
        )

        self._config_path: Path | None = None
        self._config_data: dict[str, Any]
        self._config_stem: str

        if isinstance(config, dict):
            self._config_data = dict(config)
            self._config_stem = (
                name
                or section_name(self._config_data, "run")
                or "unnamed"
            )
        else:
            path = Path(config)
            if path.is_file() or (path.suffix == ".toml" and path.parent.exists()):
                resolved = path if path.is_absolute() else (workspace_root() / path)
                if not resolved.is_file():
                    resolved = resolveConfigPath(config)
            else:
                resolved = resolveConfigPath(config)
            self._config_path = resolved
            self._config_data = load_toml(resolved)
            self._config_stem = resolved.stem

        run_sec = dict(self._config_data.get("run") or {})
        self._name = name or run_sec.get("name") or self._config_stem
        base_params = dict(self._config_data.get("params") or {})
        base_params.update(self._params_overlay)
        self._params = base_params
        self._fingerprint_keys = list(run_sec.get("fingerprint_keys") or [])

        self._id: str | None = None
        self._dir: Path | None = None
        self._status = "constructed"
        self._metrics: dict[str, Any] = {"run": {}, "items": {}}
        self._pins: dict[str, str] = {}
        self._entered = False
        self._scope: Scope | None = None
        self.handoff_artifacts: dict[str, Path] = {}

        if self._fingerprint_override:
            self._fingerprint = self._fingerprint_override
        else:
            self._fingerprint = compute_fingerprint(
                self._config_stem, self._params, self._fingerprint_keys
            )

    def _bind_scope(self) -> Scope:
        assert self._id is not None
        self._scope = Scope(layer="run", id=self._id, dir=self._dir)
        return self._scope

    @property
    def scope(self) -> Scope:
        if self._scope is None:
            raise RuntimeError("Run not entered")
        return self._scope

    # --- properties ---

    @property
    def id(self) -> str:
        if self._id is None:
            raise RuntimeError("Run not entered")
        return self._id

    @property
    def dir(self) -> Path:
        if self._dir is None:
            raise RuntimeError("Run not entered")
        return self._dir

    @property
    def status(self) -> str:
        return self._status

    @property
    def params(self) -> dict:
        return self._params

    @property
    def fingerprint(self) -> str:
        return self._fingerprint

    @property
    def config_stem(self) -> str:
        return self._config_stem

    @property
    def config_data(self) -> dict[str, Any]:
        return self._config_data

    @property
    def parent(self) -> dict | None:
        return self._parent

    # --- context manager ---

    def __enter__(self) -> Run:
        rid, path = self.ledger.allocate_run_dir(str(self._name))
        self._id = rid
        self._dir = path
        self._status = "running"
        self._bind_scope()
        now = utc_now_iso()

        snap = dict(self._config_data)
        snap_run = dict(snap.get("run") or {})
        snap_run["name"] = self._name
        snap["run"] = snap_run
        snap["params"] = dict(self._params)
        dump_toml(snap, path / "config.toml")

        meta = {
            "id": rid,
            "layer": "run",
            "status": "running",
            "config_stem": self._config_stem,
            "name": self._name,
            "created_at": now,
            "updated_at": now,
            "finished_at": None,
            "paths": {
                "dir": self.ledger._rel(path),
                "config": "config.toml",
                "log": "log.txt",
            },
            "fingerprint": self._fingerprint,
            "pins": {},
            "parent": self._parent,
        }
        write_metadata(path, meta)
        write_metrics(path, self._metrics)
        (path / "log.txt").touch()
        self._entered = True

        if self._handoff_artifacts_in:
            handoff_dir = path / "handoff"
            handoff_dir.mkdir(parents=True, exist_ok=True)
            for stem, src in self._handoff_artifacts_in.items():
                src_path = Path(src)
                dest_name = src_path.name if src_path.suffix else stem
                if not Path(dest_name).suffix and src_path.suffix:
                    dest_name = f"{stem}{src_path.suffix}"
                elif not Path(stem).suffix and src_path.suffix:
                    dest_name = f"{stem}{src_path.suffix}"
                else:
                    dest_name = Path(stem).name
                    if src_path.suffix and not Path(dest_name).suffix:
                        dest_name = f"{dest_name}{src_path.suffix}"
                dest = handoff_dir / dest_name
                if src_path.is_file():
                    dest.write_bytes(src_path.read_bytes())
                self.handoff_artifacts[stem] = dest

        self.write_to_log(f"run started id={rid} fingerprint={self._fingerprint}")
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if not self._entered:
            return False
        if self._status == "running":
            if exc_type is PreflightCancel:
                self._mark_cancelled(str(exc) if exc else "preflight cancel")
                return True
            if exc_type is not None:
                self.fail(exc)
            else:
                self.complete()
        return False

    def _flush_meta(self, **updates: Any) -> None:
        meta = read_metadata(self.dir)
        meta.update(updates)
        meta["updated_at"] = utc_now_iso()
        meta["pins"] = dict(self._pins)
        write_metadata(self.dir, meta)

    def _require_running(self) -> None:
        if self._status != "running":
            raise RuntimeError(f"run is {self._status}, expected running")

    def _emit_metrics(self) -> None:
        self.sink.emit(self.scope, MetricSet(dict(self._metrics)))

    # --- preflight ---

    def check_config(self) -> bool:
        """Structural defaults. Override for custom checks."""
        if not self._name:
            raise PreflightCancel("run name is required")
        data_sec = self._config_data.get("data") or {}
        root = data_sec.get("root")
        if root:
            p = Path(root)
            if not p.is_absolute():
                candidates = [
                    workspace_root() / p,
                    workspace_root() / "bench_run" / p,
                ]
                if not any(c.exists() for c in candidates):
                    raise PreflightCancel(f"data.root does not exist: {root}")
        return True

    def preflight(self) -> bool:
        self._require_running()
        try:
            ok = self.check_config()
            if ok is False:
                raise PreflightCancel("check_config returned False")
            if self._preflight_hook is not None:
                hook_ok = self._preflight_hook(self)
                if hook_ok is False:
                    raise PreflightCancel("preflight_hook returned False")
        except PreflightCancel as exc:
            self._mark_cancelled(str(exc) or "preflight cancel")
            raise
        return True

    def _mark_cancelled(self, reason: str = "") -> None:
        self._status = "cancelled"
        now = utc_now_iso()
        self._flush_meta(status="cancelled", finished_at=now, error=reason or None)
        try:
            self.ledger.cancel_run(self.id, reason)
        except Exception:
            pass
        self.write_to_log(f"cancelled: {reason}")

    # --- telemetry ---

    def add_metric(self, key: str, value: Any) -> None:
        self._require_running()
        self._metrics.setdefault("run", {})[key] = value
        self._emit_metrics()

    def add_item_metric(self, item_id: str, key: str, value: Any) -> None:
        self._require_running()
        items = self._metrics.setdefault("items", {})
        items.setdefault(item_id, {})[key] = value
        self._emit_metrics()

    def add_item_metrics(self, item_id: str, mapping: dict[str, Any]) -> None:
        self._require_running()
        items = self._metrics.setdefault("items", {})
        items.setdefault(item_id, {}).update(mapping)
        self._emit_metrics()

    def get_metrics(self) -> dict:
        return self._metrics

    def write_to_log(self, msg: str) -> None:
        if self._scope is None:
            return
        self.sink.emit(self._scope, LogLine(msg))

    def progress_line(self, msg: str) -> None:
        if self._scope is None:
            return
        self.sink.emit(self._scope, ProgressLine(msg))

    @contextmanager
    def progress_bar(
        self,
        total: int | None = None,
        *,
        title: str | None = None,
        console: bool | None = None,
        tty_bar: bool | None = None,
    ) -> Iterator[Any]:
        with self.sink.progress_bar(
            self.scope, total, title=title, tty_bar=tty_bar
        ) as bar:
            yield bar

    # --- orchestration IO (Ledger) ---

    def output_path(self, *parts: str) -> Path:
        self._require_running()
        out = self.dir.joinpath("output", *parts)
        out.parent.mkdir(parents=True, exist_ok=True)
        return out

    def write_output(self, name: str, data: bytes | str) -> Path:
        self._require_running()
        path = self.output_path(name)
        if isinstance(data, str):
            path.write_text(data, encoding="utf-8")
            raw = data.encode("utf-8")
        else:
            path.write_bytes(data)
            raw = data
        try:
            self.ledger.put_output(self.id, f"output/{name}", raw)
        except Exception:
            pass
        return path

    def pin_artifact(self, stem: str, path: str | Path) -> None:
        self._require_running()
        p = Path(path)
        if p.is_absolute():
            try:
                rel = p.relative_to(self.dir)
            except ValueError:
                rel = p
            rel_s = str(rel).replace("\\", "/")
        else:
            rel_s = str(path).replace("\\", "/")
        self._pins[stem] = rel_s
        self._flush_meta()

    def complete(self) -> None:
        if self._status != "running":
            return
        self._status = "complete"
        now = utc_now_iso()
        self._emit_metrics()
        self._flush_meta(status="complete", finished_at=now)
        self.ledger.complete_run(self.id)
        self.write_to_log("complete")

    def fail(self, exc: BaseException | None = None) -> None:
        if self._status != "running":
            return
        self._status = "failed"
        now = utc_now_iso()
        err = ""
        if exc is not None:
            err = f"{type(exc).__name__}: {exc}"
            self.write_to_log(err)
            self.write_to_log(traceback.format_exc())
        self._emit_metrics()
        self._flush_meta(status="failed", finished_at=now, error=err or None)
        self.ledger.fail_run(self.id, err or "failed")
        self.write_to_log("failed")

    @classmethod
    def resume(cls, results_dir: str | Path, **kwargs: Any) -> Run | None:
        """Reopen a running Run dir; terminal → return None (no-op)."""
        d = Path(results_dir)
        meta = read_metadata(d)
        status = meta.get("status")
        if status in ("complete", "failed", "cancelled"):
            return None
        config_path = d / "config.toml"
        data = load_toml(config_path) if config_path.is_file() else {"run": {"name": meta.get("name")}}
        run = cls(data, name=meta.get("name"), **kwargs)
        run._id = meta["id"]
        run._dir = d
        run._status = "running"
        run._entered = True
        run._fingerprint = meta.get("fingerprint") or run._fingerprint
        run._pins = dict(meta.get("pins") or {})
        run._bind_scope()
        run.ledger.register_run_dir(run._id, d)
        return run
