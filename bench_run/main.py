"""CLI entry: local drive, coordinator server, worker claim loop."""

from __future__ import annotations

import argparse
import os
import sys
import threading
from pathlib import Path
from typing import Callable

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


def main(runner: Callable[[Run], None], argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    log_to_console = not args.no_console_log

    if args.role == "coordinator":
        return _role_coordinator(args, runner, log_to_console=log_to_console)
    if args.role == "worker":
        return _role_worker(args, runner, log_to_console=log_to_console)

    # local
    if args.resume and not args.config:
        return _local_resume(args.resume, runner, log_to_console=log_to_console)

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
        return _local_resume(args.resume, runner, log_to_console=log_to_console)

    try:
        if kind == "run":
            return _drive_run(
                path, data, runner, name=args.name, log_to_console=log_to_console
            )
        if kind == "matrix":
            return _drive_matrix(
                path,
                data,
                runner,
                name=args.name,
                cell_ids=args.cell_ids or None,
                log_to_console=log_to_console,
            )
        if kind == "campaign":
            return _drive_campaign(
                path,
                data,
                runner,
                name=args.name,
                phase_ids=args.phase_ids or None,
                log_to_console=log_to_console,
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


def _role_coordinator(args: argparse.Namespace, runner: Callable, *, log_to_console: bool) -> int:
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

    from bench_run.server.app import create_app
    from bench_run.server.store import ServerStore

    store = ServerStore(data_dir, lease_scan_s=lease_scan_s)
    app = create_app(store, token=token)

    exp: tuple[Path, str, dict] | None = None
    if len(args.config) == 2:
        try:
            exp = _resolve_experiment(args.config[1])
        except ConfigError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    if args.resume and exp is None:
        # resume against in-process store
        def drive_resume() -> None:
            d = Path(args.resume)
            if not d.is_absolute():
                d = workspace_root() / d
            from bench_run.artifacts import read_metadata

            meta = read_metadata(d)
            if meta.get("layer") == "matrix":
                m = MatrixRun.resume(d, ledger=store)
                m.execute(None, distributed=True)
            elif meta.get("layer") == "campaign":
                c = CampaignRun.resume(d, ledger=store)
                c.execute(None, distributed=True)

        threading.Thread(target=drive_resume, daemon=True).start()
    elif exp is not None:
        path, kind, data = exp

        def drive_exp() -> None:
            if kind == "matrix":
                m = MatrixRun(
                    data,
                    name=args.name,
                    cell_ids=args.cell_ids or None,
                    ledger=store,
                )
                m.execute(None, distributed=True)
            elif kind == "campaign":
                c = CampaignRun(
                    data,
                    name=args.name,
                    phase_ids=args.phase_ids or None,
                    ledger=store,
                )
                c.execute(None, distributed=True)
            elif kind == "run":
                # single run: enqueue as one-cell synthetic — skip; not typical
                pass

        threading.Thread(target=drive_exp, daemon=True).start()

    host, _, port_s = bind.partition(":")
    port = int(port_s or "8000")
    try:
        import uvicorn

        uvicorn.run(app, host=host or "0.0.0.0", port=port, log_level="info", workers=1)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4
    finally:
        store.close()
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
    from bench_run.worker import worker_loop

    ledger = CoordinatorLedger(url, token=token)
    try:
        worker_loop(
            runner,
            ledger,
            poll_s=poll_s,
            lease_s=lease_s,
            filters=filters or None,
            log_to_console=log_to_console,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4
    finally:
        ledger.close()
    return 0


def _drive_run(
    path: Path,
    data: dict,
    runner: Callable[[Run], None],
    *,
    name: str | None,
    log_to_console: bool,
) -> int:
    try:
        with Run(path, name=name, log_to_console=log_to_console) as run:
            run.preflight()
            runner(run)
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
) -> int:
    def wrapped(run: Run) -> None:
        run._log_to_console = log_to_console
        runner(run)

    matrix = MatrixRun(path, name=name, cell_ids=cell_ids)
    matrix.execute(wrapped)
    any_cancel = any(c["status"] == "cancelled" for c in matrix._manifest["cells"])
    any_fail = any(c["status"] == "failed" for c in matrix._manifest["cells"])
    if any_cancel and not any(c["status"] == "ok" for c in matrix._manifest["cells"]):
        return 3
    if any_fail and not any(c["status"] == "ok" for c in matrix._manifest["cells"]):
        return 2
    return 0


def _drive_campaign(
    path: Path,
    data: dict,
    runner: Callable[[Run], None],
    *,
    name: str | None,
    phase_ids: list[str] | None,
    log_to_console: bool,
) -> int:
    def wrapped(run: Run) -> None:
        run._log_to_console = log_to_console
        runner(run)

    campaign = CampaignRun(
        path,
        name=name,
        phase_ids=phase_ids,
    )
    campaign.execute(wrapped)
    if campaign.status == "cancelled":
        return 3
    if campaign.status == "failed":
        return 2
    return 0


def _local_resume(
    results_dir: str,
    runner: Callable[[Run], None],
    *,
    log_to_console: bool,
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

    if layer == "run":
        if status in ("complete", "failed", "cancelled"):
            return 0
        run = Run.resume(d, log_to_console=log_to_console)
        if run is None:
            return 0
        try:
            runner(run)
            if run.status == "running":
                run.complete()
        except Exception as exc:
            run.fail(exc)
            return 2
        finally:
            run._close_log()
        return 0 if run.status == "complete" else (3 if run.status == "cancelled" else 2)

    if layer == "matrix":
        matrix = MatrixRun.resume(d)
        if matrix.status in ("complete", "cancelled"):
            return 0
        matrix.execute(runner)
        return 0

    if layer == "campaign":
        campaign = CampaignRun.resume(d)
        if campaign.status in ("complete", "cancelled"):
            return 0
        campaign.execute(runner)
        if campaign.status == "cancelled":
            return 3
        if campaign.status == "failed":
            return 2
        return 0

    print(f"error: unknown layer {layer!r}", file=sys.stderr)
    return 1
