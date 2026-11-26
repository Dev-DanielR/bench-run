"""CLI entry: parse argv, resolve configs, dispatch to execution runners."""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path
from typing import Callable

from bench_run.config import (
    ConfigError,
    classify_config,
    load_toml,
    resolve_config_for_local,
    resolve_execution_config_path,
    workspace_root,
)
from bench_run.execution import local as local_exec
from bench_run.extras import COORD_EXTRA_HINT
from bench_run.layers.run import Run


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bench_run", description="bench-run experiment harness")
    p.add_argument(
        "--config",
        action="append",
        default=[],
        metavar="NAME|PATH",
        help="Experiment or execution config (repeatable)",
    )
    p.add_argument(
        "--role",
        choices=("coordinator", "worker"),
        default=None,
        help="Device role; omit for local drive",
    )
    p.add_argument("--resume", metavar="DIR", default=None, help="Resume results directory")
    p.add_argument("--name", default=None, help="Override result dir stem")
    p.add_argument(
        "--cell-id",
        action="append",
        default=[],
        dest="cell_ids",
        help="Matrix cell filter (repeatable)",
    )
    p.add_argument(
        "--phase-id",
        action="append",
        default=[],
        dest="phase_ids",
        help="Campaign phase filter (repeatable)",
    )
    p.add_argument(
        "--no-console-log",
        action="store_true",
        help="Disable console log mirror",
    )
    p.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable TTY progress bars (status lines still go to log files)",
    )
    p.add_argument(
        "--until-done",
        action="store_true",
        help="Coordinator/worker: exit when the experiment finishes (or worker idle/coord down)",
    )
    p.add_argument(
        "--idle-polls",
        type=int,
        default=5,
        metavar="N",
        help="With --until-done on worker: exit after N consecutive empty claims (default 5)",
    )
    return p


def _resolve_execution(name: str) -> tuple[Path, dict]:
    p = Path(name)
    if p.is_absolute() or "/" in str(name).replace("\\", "/") or "\\" in str(name):
        if not p.is_absolute():
            p = (workspace_root() / p).resolve()
        if not p.is_file():
            raise ConfigError(f"config not found: {name}")
        data = load_toml(p)
        kind = classify_config(p, data)
        if kind != "execution":
            raise ConfigError(f"expected execution config, got {kind}")
        return p, data
    path = resolve_execution_config_path(name)
    data = load_toml(path)
    return path, data


def _load_run_coordinator():
    try:
        mod = importlib.import_module("bench_run.execution.server.coordinator")
    except ImportError as exc:
        print(f"error: {COORD_EXTRA_HINT}\n({exc})", file=sys.stderr)
        return None
    return mod.run_coordinator


def _load_worker():
    try:
        return importlib.import_module("bench_run.execution.worker")
    except ImportError as exc:
        print(f"error: {COORD_EXTRA_HINT}\n({exc})", file=sys.stderr)
        return None


def main(
    runner: Callable[[Run], None],
    argv: list[str] | None = None,
    *,
    preflight_hook: Callable[[Run], bool | None] | None = None,
) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    log_to_console = not args.no_console_log
    tty_bar = not args.no_progress

    if args.role == "coordinator":
        if not args.config:
            print("error: coordinator requires execution --config", file=sys.stderr)
            return 1
        if len(args.config) > 2:
            print(
                "error: coordinator expects execution config and optional experiment",
                file=sys.stderr,
            )
            return 1
        try:
            _epath, edata = _resolve_execution(args.config[0])
        except ConfigError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        exp: tuple[Path, str, dict] | None = None
        if len(args.config) == 2:
            try:
                exp = resolve_config_for_local(args.config[1])
            except ConfigError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
            except Exception as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
        run_coordinator = _load_run_coordinator()
        if run_coordinator is None:
            return 1
        return run_coordinator(
            edata,
            runner,
            experiment=exp,
            resume=args.resume,
            name=args.name,
            cell_ids=args.cell_ids or None,
            phase_ids=args.phase_ids or None,
            until_done=bool(args.until_done),
            log_to_console=log_to_console,
            tty_bar=tty_bar,
        )

    if args.role == "worker":
        if not args.config or len(args.config) != 1:
            print("error: worker expects exactly one execution --config", file=sys.stderr)
            return 1
        try:
            _epath, edata = _resolve_execution(args.config[0])
        except ConfigError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        worker_exec = _load_worker()
        if worker_exec is None:
            return 1
        return worker_exec.run(
            edata,
            runner,
            until_done=bool(args.until_done),
            idle_polls=int(args.idle_polls),
            log_to_console=log_to_console,
            preflight_hook=preflight_hook,
        )

    # local
    if args.resume and not args.config:
        return local_exec.resume(
            args.resume,
            runner,
            log_to_console=log_to_console,
            tty_bar=tty_bar,
            preflight_hook=preflight_hook,
        )

    if not args.config:
        print("error: --config is required (unless --resume alone)", file=sys.stderr)
        return 1

    if len(args.config) != 1:
        print(
            f"error: local mode expects exactly one experiment config, got {len(args.config)}",
            file=sys.stderr,
        )
        return 1

    try:
        path, kind, data = resolve_config_for_local(args.config[0])
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.resume:
        return local_exec.resume(
            args.resume,
            runner,
            log_to_console=log_to_console,
            tty_bar=tty_bar,
            preflight_hook=preflight_hook,
        )

    try:
        return local_exec.run(
            path,
            kind,
            data,
            runner,
            name=args.name,
            cell_ids=args.cell_ids or None,
            phase_ids=args.phase_ids or None,
            log_to_console=log_to_console,
            tty_bar=tty_bar,
            preflight_hook=preflight_hook,
        )
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
