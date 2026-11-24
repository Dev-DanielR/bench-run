"""CLI entry: local drive, coordinator server, worker claim loop."""

from __future__ import annotations

import argparse
import os
import sys
import threading
from pathlib import Path
from typing import Any, Callable

from bench_run.campaign import CampaignRun
from bench_run.config import (
    ConfigError,
    classify_config,
    load_toml,
    resolveExecutionConfigPath,
    resolve_config_for_local,
    workspace_root,
)
from bench_run.matrix import MatrixRun
from bench_run.run import PreflightCancel, Run


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
    path = resolveExecutionConfigPath(name)
    data = load_toml(path)
    return path, data


def _resolve_experiment(name: str) -> tuple[Path, str, dict]:
    return resolve_config_for_local(name)


def _tty_bar_from_args(args: argparse.Namespace) -> bool:
    return not args.no_progress


def main(runner: Callable[[Run], None], argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    log_to_console = not args.no_console_log
    tty_bar = _tty_bar_from_args(args)

    if args.role == "coordinator":
        return _role_coordinator(
            args, runner, log_to_console=log_to_console, tty_bar=tty_bar
        )
    if args.role == "worker":
        return _role_worker(args, runner, log_to_console=log_to_console)

    # local
    if args.resume and not args.config:
        return _local_resume(
            args.resume,
            runner,
            log_to_console=log_to_console,
            tty_bar=tty_bar,
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
        return _local_resume(
            args.resume,
            runner,
            log_to_console=log_to_console,
            tty_bar=tty_bar,
        )

    try:
        if kind == "run":
            return _drive_run(
                path,
                data,
                runner,
                name=args.name,
                log_to_console=log_to_console,
                tty_bar=tty_bar,
            )
        if kind == "matrix":
            return _drive_matrix(
                path,
                data,
                runner,
                name=args.name,
                cell_ids=args.cell_ids or None,
                log_to_console=log_to_console,
                tty_bar=tty_bar,
            )
        if kind == "campaign":
            return _drive_campaign(
                path,
                data,
                runner,
                name=args.name,
                phase_ids=args.phase_ids or None,
                log_to_console=log_to_console,
                tty_bar=tty_bar,
            )
        print(f"error: unsupported config kind {kind!r} for local mode", file=sys.stderr)
        return 1
    except PreflightCancel:
        return 3
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _layer_exit_code(layer: Any) -> int:
    status = getattr(layer, "status", None)
    if status == "cancelled":
        return 3
    if status == "failed":
        return 2
    if hasattr(layer, "_manifest") and isinstance(getattr(layer, "_manifest", None), dict):
        cells = layer._manifest.get("cells") or []
        if cells:
            any_cancel = any(c.get("status") == "cancelled" for c in cells)
            any_fail = any(c.get("status") == "failed" for c in cells)
            any_ok = any(c.get("status") == "ok" for c in cells)
            if any_cancel and not any_ok:
                return 3
            if any_fail and not any_ok:
                return 2
    return 0


def _role_coordinator(
    args: argparse.Namespace,
    runner: Callable,
    *,
    log_to_console: bool,
    tty_bar: bool,
) -> int:
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

    csec = dict(edata.get("coordinator") or {})
    bind = csec.get("bind")
    if not bind:
        print("error: coordinator.bind required", file=sys.stderr)
        return 1
    data_dir = csec.get("data_dir")
    if data_dir:
        data_dir = Path(data_dir)
        if not data_dir.is_absolute():
            data_dir = workspace_root() / data_dir
    else:
        data_dir = workspace_root() / "bench_run" / "results" / "_coordinator"
    auth = csec.get("auth") or {}
    token_env = auth.get("token_env")
    token = os.environ.get(token_env) if token_env else None
    lease_scan_s = float(csec.get("lease_scan_s") or 10.0)

    until_done = bool(args.until_done)
    exp: tuple[Path, str, dict] | None = None
    if len(args.config) == 2:
        try:
            exp = _resolve_experiment(args.config[1])
        except ConfigError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    if until_done and exp is None and not args.resume:
        print(
            "error: --until-done requires an experiment --config or --resume",
            file=sys.stderr,
        )
        return 1

    from bench_run.server.app import create_app
    from bench_run.server.store import ServerStore

    store = ServerStore(data_dir, lease_scan_s=lease_scan_s)
    app = create_app(store, token=token)

    drive_result: dict[str, Any] = {"code": 0, "error": None, "done": threading.Event()}
    layer_holder: dict[str, Any] = {"layer": None}

    def _finish_drive(code: int = 0, error: BaseException | None = None) -> None:
        drive_result["code"] = code
        drive_result["error"] = error
        drive_result["done"].set()

    if args.resume and exp is None:

        def drive_resume() -> None:
            try:
                d = Path(args.resume)
                if not d.is_absolute():
                    d = workspace_root() / d
                from bench_run.artifacts import read_metadata

                meta = read_metadata(d)
                sink = _make_local_sink(
                    log_to_console=log_to_console, tty_bar=tty_bar
                )
                if meta.get("layer") == "matrix":
                    m = MatrixRun.resume(d, ledger=store, sink=sink)
                    layer_holder["layer"] = m
                    m.execute(None, distributed=True)
                    _finish_drive(_layer_exit_code(m))
                elif meta.get("layer") == "campaign":
                    c = CampaignRun.resume(d, ledger=store, sink=sink)
                    layer_holder["layer"] = c
                    c.execute(None, distributed=True)
                    _finish_drive(_layer_exit_code(c))
                else:
                    _finish_drive(1)
            except BaseException as exc:
                _finish_drive(4, exc)

        threading.Thread(target=drive_resume, daemon=True).start()
    elif exp is not None:
        path, kind, data = exp

        def drive_exp() -> None:
            try:
                sink = _make_local_sink(
                    log_to_console=log_to_console, tty_bar=tty_bar
                )
                if kind == "matrix":
                    m = MatrixRun(
                        data,
                        name=args.name,
                        cell_ids=args.cell_ids or None,
                        ledger=store,
                        sink=sink,
                    )
                    layer_holder["layer"] = m
                    m.execute(None, distributed=True)
                    _finish_drive(_layer_exit_code(m))
                elif kind == "campaign":
                    c = CampaignRun(
                        data,
                        name=args.name,
                        phase_ids=args.phase_ids or None,
                        ledger=store,
                        sink=sink,
                    )
                    layer_holder["layer"] = c
                    c.execute(None, distributed=True)
                    _finish_drive(_layer_exit_code(c))
                elif kind == "run":
                    _finish_drive(0)
                else:
                    _finish_drive(1)
            except BaseException as exc:
                _finish_drive(2, exc)

        threading.Thread(target=drive_exp, daemon=True).start()
    elif until_done:
        _finish_drive(0)

    host, _, port_s = bind.partition(":")
    port = int(port_s or "8000")
    try:
        import uvicorn

        config = uvicorn.Config(
            app, host=host or "0.0.0.0", port=port, log_level="info", workers=1
        )
        server = uvicorn.Server(config)

        if until_done:

            def _watch_done() -> None:
                drive_result["done"].wait()
                server.should_exit = True

            threading.Thread(target=_watch_done, daemon=True).start()

        server.run()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4
    finally:
        store.close()

    if until_done:
        if drive_result["error"] is not None:
            print(f"error: {drive_result['error']}", file=sys.stderr)
        return int(drive_result["code"])
    return 0


def _role_worker(args: argparse.Namespace, runner: Callable, *, log_to_console: bool) -> int:
    if not args.config or len(args.config) != 1:
        print("error: worker expects exactly one execution --config", file=sys.stderr)
        return 1
    try:
        _epath, edata = _resolve_execution(args.config[0])
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    wsec = dict(edata.get("worker") or {})
    url = wsec.get("url")
    if not url:
        print("error: worker.url required", file=sys.stderr)
        return 1
    auth = wsec.get("auth") or {}
    token_env = auth.get("token_env")
    token = os.environ.get(token_env) if token_env else None
    claim = dict(wsec.get("claim") or {})
    poll_s = float(claim.get("poll_s") or 2.0)
    lease_s = int(claim.get("lease_s") or 300)
    filters: dict = {}
    for key in ("matrix_ids", "campaign_ids", "config_stems"):
        vals = claim.get(key) or []
        if vals:
            filters[key] = list(vals)

    from bench_run.ledger.coordinator import CoordinatorLedger
    from bench_run.sink.coordinator import CoordinatorSink
    from bench_run.worker import worker_loop

    sink = CoordinatorSink(log_to_console=log_to_console, tty_bar=False)
    ledger = CoordinatorLedger(url, token=token, sink=sink)
    try:
        code = worker_loop(
            runner,
            ledger,
            poll_s=poll_s,
            lease_s=lease_s,
            filters=filters or None,
            log_to_console=log_to_console,
            until_done=bool(args.until_done),
            idle_polls=int(args.idle_polls),
            health_url=url.rstrip("/") + "/health",
        )
        return int(code)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4
    finally:
        ledger.close()


def _make_local_sink(*, log_to_console: bool, tty_bar: bool):
    from bench_run.sink.local import LocalFsSink

    return LocalFsSink(log_to_console=log_to_console, tty_bar=tty_bar)


def _drive_run(
    path: Path,
    data: dict,
    runner: Callable[[Run], None],
    *,
    name: str | None,
    log_to_console: bool,
    tty_bar: bool,
) -> int:
    sink = _make_local_sink(log_to_console=log_to_console, tty_bar=tty_bar)
    try:
        with Run(path, name=name, sink=sink) as run:
            run.preflight()
            run.progress_line(f"run body start id={run.id}")
            with run.progress_bar(None, title=f"run:{run.config_stem}"):
                runner(run)
            run.progress_line(f"run body end status={run.status}")
        if run.status == "cancelled":
            return 3
        if run.status == "failed":
            return 2
        return 0
    except PreflightCancel:
        return 3


def _drive_matrix(
    path: Path,
    data: dict,
    runner: Callable[[Run], None],
    *,
    name: str | None,
    cell_ids: list[str] | None,
    log_to_console: bool,
    tty_bar: bool,
) -> int:
    sink = _make_local_sink(log_to_console=log_to_console, tty_bar=tty_bar)
    matrix = MatrixRun(
        path,
        name=name,
        cell_ids=cell_ids,
        sink=sink,
    )
    matrix.execute(runner)
    return _layer_exit_code(matrix)


def _drive_campaign(
    path: Path,
    data: dict,
    runner: Callable[[Run], None],
    *,
    name: str | None,
    phase_ids: list[str] | None,
    log_to_console: bool,
    tty_bar: bool,
) -> int:
    sink = _make_local_sink(log_to_console=log_to_console, tty_bar=tty_bar)
    campaign = CampaignRun(
        path,
        name=name,
        phase_ids=phase_ids,
        sink=sink,
    )
    campaign.execute(runner)
    return _layer_exit_code(campaign)


def _local_resume(
    results_dir: str,
    runner: Callable[[Run], None],
    *,
    log_to_console: bool,
    tty_bar: bool,
) -> int:
    d = Path(results_dir)
    if not d.is_absolute():
        d = workspace_root() / d
    if not d.is_dir():
        print(f"error: resume dir not found: {results_dir}", file=sys.stderr)
        return 1
    meta_path = d / "metadata.json"
    if not meta_path.is_file():
        print(f"error: no metadata.json in {results_dir}", file=sys.stderr)
        return 1
    from bench_run.artifacts import read_metadata

    meta = read_metadata(d)
    layer = meta.get("layer")
    status = meta.get("status")

    sink = _make_local_sink(log_to_console=log_to_console, tty_bar=tty_bar)

    if layer == "run":
        if status in ("complete", "failed", "cancelled"):
            return 0
        run = Run.resume(d, sink=sink)
        if run is None:
            return 0
        try:
            with run.progress_bar(None, title=f"run:{run.config_stem}"):
                runner(run)
            if run.status == "running":
                run.complete()
        except Exception as exc:
            run.fail(exc)
            return 2
        return 0 if run.status == "complete" else (3 if run.status == "cancelled" else 2)

    if layer == "matrix":
        matrix = MatrixRun.resume(d, sink=sink)
        if matrix.status in ("complete", "cancelled"):
            return 0
        matrix.execute(runner)
        return _layer_exit_code(matrix)

    if layer == "campaign":
        campaign = CampaignRun.resume(d, sink=sink)
        if campaign.status in ("complete", "cancelled"):
            return 0
        campaign.execute(runner)
        return _layer_exit_code(campaign)

    print(f"error: unknown layer {layer!r}", file=sys.stderr)
    return 1
