"""Starlette coordinator app: /health + /v1/* REST."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Callable

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from bench_run.config import dump_toml, load_toml, workspace_root
from bench_run.ledger.base import RunPackage
from bench_run.execution.server.store import ConflictError, ServerStore


def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": code, "message": message}, status_code=status)


def create_app(
    store: ServerStore | None = None,
    *,
    data_dir: Path | str | None = None,
    token: str | None = None,
    token_env: str | None = None,
    runner: Callable | None = None,
) -> Starlette:
    if store is None:
        store = ServerStore(data_dir)
    if token is None and token_env:
        token = os.environ.get(token_env)

    app = Starlette(routes=[])
    app.state.store = store
    app.state.token = token
    app.state.runner = runner
    app.state.drive_threads: list[threading.Thread] = []

    async def auth_check(request: Request) -> JSONResponse | None:
        expected = app.state.token
        if not expected:
            return None
        hdr = request.headers.get("authorization") or request.headers.get("Authorization")
        if not hdr or not hdr.lower().startswith("bearer "):
            return _err(401, "unauthorized", "missing bearer token")
        got = hdr.split(" ", 1)[1].strip()
        if got != expected:
            return _err(401, "unauthorized", "invalid bearer token")
        return None

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    async def post_claims(request: Request) -> Response:
        denied = await auth_check(request)
        if denied:
            return denied
        try:
            body = await request.json()
        except Exception:
            return _err(400, "validation_error", "invalid JSON body")
        worker_id = body.get("worker_id")
        if not worker_id:
            return _err(400, "validation_error", "worker_id required")
        lease_s = int(body.get("lease_s") or 300)
        filters = body.get("filters")
        spec = store.claim_run(worker_id=worker_id, lease_s=lease_s, filters=filters)
        if spec is None:
            return Response(status_code=204)
        return JSONResponse(spec)

    async def post_heartbeat(request: Request) -> Response:
        denied = await auth_check(request)
        if denied:
            return denied
        claim_id = request.path_params["claim_id"]
        try:
            store.heartbeat_claim(claim_id)
        except KeyError:
            return _err(410, "gone", f"claim expired or unknown: {claim_id}")
        return JSONResponse({"ok": True})

    async def delete_claim(request: Request) -> Response:
        denied = await auth_check(request)
        if denied:
            return denied
        claim_id = request.path_params["claim_id"]
        store.release_claim(claim_id)
        return JSONResponse({"ok": True})

    async def get_run(request: Request) -> Response:
        denied = await auth_check(request)
        if denied:
            return denied
        run_id = request.path_params["run_id"]
        try:
            return JSONResponse(store.get_run(run_id))
        except KeyError:
            return _err(404, "not_found", f"run not found: {run_id}")

    async def put_package(request: Request) -> Response:
        denied = await auth_check(request)
        if denied:
            return denied
        run_id = request.path_params["run_id"]
        try:
            store.run_dir(run_id)
        except KeyError:
            return _err(404, "not_found", f"run not found: {run_id}")

        ct = request.headers.get("content-type", "")
        package: RunPackage
        if "multipart/form-data" in ct:
            form = await request.form()
            known = {"metadata", "metrics", "config_toml", "log", "artifact"}
            for key in form.keys():
                if key not in known:
                    return _err(400, "validation_error", f"unknown part: {key}")
            meta_raw = form.get("metadata")
            if meta_raw is None:
                return _err(400, "validation_error", "metadata part required")
            if hasattr(meta_raw, "read"):
                meta_bytes = await meta_raw.read()
                metadata = json.loads(meta_bytes.decode("utf-8"))
            else:
                metadata = json.loads(str(meta_raw))
            metrics_raw = form.get("metrics")
            if metrics_raw is None:
                metrics: dict = {}
            elif hasattr(metrics_raw, "read"):
                metrics = json.loads((await metrics_raw.read()).decode("utf-8") or "{}")
            else:
                metrics = json.loads(str(metrics_raw) or "{}")
            config_toml = ""
            log_text = ""
            ct_part = form.get("config_toml")
            if ct_part is not None:
                if hasattr(ct_part, "read"):
                    config_toml = (await ct_part.read()).decode("utf-8")
                else:
                    config_toml = str(ct_part)
            log_part = form.get("log")
            if log_part is not None:
                if hasattr(log_part, "read"):
                    log_text = (await log_part.read()).decode("utf-8")
                else:
                    log_text = str(log_part)
            artifacts = []
            # starlette: multiple parts with same name
            arts = form.getlist("artifact") if hasattr(form, "getlist") else []
            if not arts and form.get("artifact") is not None:
                arts = [form.get("artifact")]
            for art in arts:
                if art is None:
                    continue
                filename = getattr(art, "filename", None) or "artifact"
                data = await art.read() if hasattr(art, "read") else bytes(art)
                artifacts.append({"relative_path": filename, "data": data})
            package = {
                "metadata": metadata,
                "metrics": metrics,
                "config_toml": config_toml,
                "log": log_text,
                "artifacts": artifacts,
            }
        else:
            try:
                body = await request.json()
            except Exception:
                return _err(400, "validation_error", "expected multipart or JSON package")
            package = body

        status = (package.get("metadata") or {}).get("status")
        if status not in ("complete", "failed", "cancelled"):
            return _err(400, "validation_error", "metadata.status must be terminal")
        try:
            record = store.apply_terminal_package(
                run_id,
                status,
                package,
                error=(package.get("metadata") or {}).get("error"),
            )
        except ConflictError as exc:
            return _err(409, "conflict", str(exc))
        except KeyError:
            return _err(404, "not_found", f"run not found: {run_id}")
        return JSONResponse(record)

    async def post_cancel(request: Request) -> Response:
        denied = await auth_check(request)
        if denied:
            return denied
        run_id = request.path_params["run_id"]
        try:
            body = await request.json()
        except Exception:
            body = {}
        reason = (body or {}).get("reason") or ""
        try:
            store.run_dir(run_id)
        except KeyError:
            return _err(404, "not_found", f"run not found: {run_id}")
        try:
            record = store.apply_terminal_package(
                run_id,
                "cancelled",
                {"metadata": {"status": "cancelled", "error": reason}, "metrics": {}},
                error=reason or None,
            )
        except ConflictError as exc:
            return _err(409, "conflict", str(exc))
        return JSONResponse(record)

    async def get_fingerprint_runs(request: Request) -> Response:
        denied = await auth_check(request)
        if denied:
            return denied
        fp = request.path_params["fingerprint"]
        limit = int(request.query_params.get("limit") or 50)
        ids = store.find_completed_runs(fp, limit=limit)
        return JSONResponse({"run_ids": ids})

    async def get_matrix_manifest(request: Request) -> Response:
        denied = await auth_check(request)
        if denied:
            return denied
        mid = request.path_params["matrix_id"]
        try:
            return JSONResponse(store.get_manifest(mid))
        except KeyError:
            return _err(404, "not_found", f"matrix not found: {mid}")

    async def get_matrix_stats(request: Request) -> Response:
        denied = await auth_check(request)
        if denied:
            return denied
        mid = request.path_params["matrix_id"]
        try:
            path = store.matrix_dir(mid) / "stats.json"
        except KeyError:
            return _err(404, "not_found", f"matrix not found: {mid}")
        if not path.is_file():
            return _err(404, "not_found", "stats not ready")
        from bench_run.fs import read_json

        return JSONResponse(read_json(path))

    async def get_matrix_compare(request: Request) -> Response:
        denied = await auth_check(request)
        if denied:
            return denied
        mid = request.path_params["matrix_id"]
        try:
            path = store.matrix_dir(mid) / "compare.json"
        except KeyError:
            return _err(404, "not_found", f"matrix not found: {mid}")
        if not path.is_file():
            return _err(404, "not_found", "compare not ready")
        from bench_run.fs import read_json

        return JSONResponse(read_json(path))

    async def get_campaign_manifest(request: Request) -> Response:
        denied = await auth_check(request)
        if denied:
            return denied
        cid = request.path_params["campaign_id"]
        try:
            return JSONResponse(store.get_manifest(cid))
        except KeyError:
            return _err(404, "not_found", f"campaign not found: {cid}")

    async def get_campaign_handoff(request: Request) -> Response:
        denied = await auth_check(request)
        if denied:
            return denied
        cid = request.path_params["campaign_id"]
        try:
            return JSONResponse(store.get_handoff(cid))
        except KeyError:
            return _err(404, "not_found", f"campaign not found: {cid}")

    async def get_campaign_winners(request: Request) -> Response:
        denied = await auth_check(request)
        if denied:
            return denied
        cid = request.path_params["campaign_id"]
        try:
            path = store.campaign_dir(cid) / "winners.json"
        except KeyError:
            return _err(404, "not_found", f"campaign not found: {cid}")
        if not path.is_file():
            return JSONResponse({"phases": {}})
        from bench_run.fs import read_json

        return JSONResponse(read_json(path))

    async def get_campaign_stats(request: Request) -> Response:
        denied = await auth_check(request)
        if denied:
            return denied
        return _err(404, "not_found", "campaigns have no stats")

    def _load_exp_config(body: dict) -> tuple[dict, str]:
        if body.get("config_toml"):
            import tomllib
            import io

            data = tomllib.loads(body["config_toml"])
            return data, body.get("name") or "exp"
        if body.get("config_path"):
            p = Path(body["config_path"])
            if not p.is_absolute():
                p = workspace_root() / p
            data = load_toml(p)
            return data, body.get("name") or p.stem
        raise ValueError("config_toml or config_path required")

    def _drive_matrix(config_data: dict, name: str | None, cell_ids: list | None) -> str:
        from bench_run.layers.matrix import MatrixRun

        m = MatrixRun(config_data, name=name, cell_ids=cell_ids, ledger=store)
        m.execute(None, distributed=True)
        return m.id

    def _drive_campaign(config_data: dict, name: str | None, phase_ids: list | None) -> str:
        from bench_run.layers.campaign import CampaignRun

        c = CampaignRun(config_data, name=name, phase_ids=phase_ids, ledger=store)
        c.execute(None, distributed=True)
        return c.id

    async def post_matrices(request: Request) -> Response:
        denied = await auth_check(request)
        if denied:
            return denied
        try:
            body = await request.json()
        except Exception:
            return _err(400, "validation_error", "invalid JSON")
        try:
            if body.get("resume_dir") and not (body.get("config_toml") or body.get("config_path")):
                from bench_run.layers.matrix import MatrixRun

                d = Path(body["resume_dir"])
                if not d.is_absolute():
                    d = store.data_dir / d
                m = MatrixRun.resume(d, ledger=store)
                mid = m.id

                def run() -> None:
                    m.execute(None, distributed=True)

                t = threading.Thread(target=run, daemon=True)
                t.start()
                app.state.drive_threads.append(t)
                return JSONResponse({"matrix_id": mid}, status_code=201)
            data, stem = _load_exp_config(body)
            name = body.get("name") or stem
            cell_ids = body.get("cell_ids")
            # open matrix synchronously to return id, drive in background
            from bench_run.layers.matrix import MatrixRun

            m = MatrixRun(data, name=name, cell_ids=cell_ids, ledger=store)
            m._open_new()
            mid = m.id

            def run() -> None:
                m.execute(None, distributed=True)

            t = threading.Thread(target=run, daemon=True)
            t.start()
            app.state.drive_threads.append(t)
            return JSONResponse({"matrix_id": mid}, status_code=201)
        except Exception as exc:
            return _err(400, "validation_error", str(exc))

    async def post_campaigns(request: Request) -> Response:
        denied = await auth_check(request)
        if denied:
            return denied
        try:
            body = await request.json()
        except Exception:
            return _err(400, "validation_error", "invalid JSON")
        try:
            data, stem = _load_exp_config(body)
            name = body.get("name") or stem
            phase_ids = body.get("phase_ids")
            from bench_run.layers.campaign import CampaignRun

            c = CampaignRun(data, name=name, phase_ids=phase_ids, ledger=store)
            c._open_new()
            cid = c.id

            def run() -> None:
                c.execute(None, distributed=True)

            t = threading.Thread(target=run, daemon=True)
            t.start()
            app.state.drive_threads.append(t)
            return JSONResponse({"campaign_id": cid}, status_code=201)
        except Exception as exc:
            return _err(400, "validation_error", str(exc))

    async def post_resume(request: Request) -> Response:
        denied = await auth_check(request)
        if denied:
            return denied
        try:
            body = await request.json()
        except Exception:
            return _err(400, "validation_error", "invalid JSON")
        results_dir = body.get("results_dir")
        layer_id = body.get("layer_id")
        d: Path | None = None
        if results_dir:
            d = Path(results_dir)
            if not d.is_absolute():
                for cand in (
                    store.data_dir / results_dir,
                    workspace_root() / results_dir,
                    store.data_dir / "matrices" / Path(results_dir).name,
                    store.data_dir / "campaigns" / Path(results_dir).name,
                ):
                    if cand.is_dir():
                        d = cand
                        break
        elif layer_id:
            for sub in ("matrices", "campaigns"):
                cand = store.data_dir / sub / layer_id
                if cand.is_dir():
                    d = cand
                    break
        if d is None or not d.is_dir():
            return _err(404, "not_found", "resume target not found")
        from bench_run.fs import read_metadata

        meta = read_metadata(d)
        layer = meta.get("layer")
        if layer == "matrix":
            from bench_run.layers.matrix import MatrixRun

            m = MatrixRun.resume(d, ledger=store)
            if m.status in ("complete", "cancelled"):
                return JSONResponse({"layer": "matrix", "id": m.id})

            def run() -> None:
                m.execute(None, distributed=True)

            t = threading.Thread(target=run, daemon=True)
            t.start()
            return JSONResponse({"layer": "matrix", "id": m.id})
        if layer == "campaign":
            from bench_run.layers.campaign import CampaignRun

            c = CampaignRun.resume(d, ledger=store)
            if c.status in ("complete", "cancelled"):
                return JSONResponse({"layer": "campaign", "id": c.id})

            def run() -> None:
                c.execute(None, distributed=True)

            t = threading.Thread(target=run, daemon=True)
            t.start()
            return JSONResponse({"layer": "campaign", "id": c.id})
        return _err(400, "validation_error", f"unsupported layer {layer}")

    async def get_artifacts(request: Request) -> Response:
        denied = await auth_check(request)
        if denied:
            return denied
        rel = request.path_params["path"]
        path = store.resolve_artifact_path(rel)
        if not path.is_file():
            return _err(404, "not_found", f"artifact not found: {rel}")
        data = path.read_bytes()
        return Response(data, media_type="application/octet-stream")

    routes = [
        Route("/health", health, methods=["GET"]),
        Route("/v1/claims", post_claims, methods=["POST"]),
        Route("/v1/claims/{claim_id}/heartbeat", post_heartbeat, methods=["POST"]),
        Route("/v1/claims/{claim_id}", delete_claim, methods=["DELETE"]),
        Route("/v1/runs/{run_id}", get_run, methods=["GET"]),
        Route("/v1/runs/{run_id}/package", put_package, methods=["PUT"]),
        Route("/v1/runs/{run_id}/cancel", post_cancel, methods=["POST"]),
        Route("/v1/fingerprints/{fingerprint:path}/runs", get_fingerprint_runs, methods=["GET"]),
        Route("/v1/matrices", post_matrices, methods=["POST"]),
        Route("/v1/matrices/{matrix_id}/manifest", get_matrix_manifest, methods=["GET"]),
        Route("/v1/matrices/{matrix_id}/stats", get_matrix_stats, methods=["GET"]),
        Route("/v1/matrices/{matrix_id}/compare", get_matrix_compare, methods=["GET"]),
        Route("/v1/campaigns", post_campaigns, methods=["POST"]),
        Route("/v1/campaigns/{campaign_id}/manifest", get_campaign_manifest, methods=["GET"]),
        Route("/v1/campaigns/{campaign_id}/handoff", get_campaign_handoff, methods=["GET"]),
        Route("/v1/campaigns/{campaign_id}/winners", get_campaign_winners, methods=["GET"]),
        Route("/v1/campaigns/{campaign_id}/stats", get_campaign_stats, methods=["GET"]),
        Route("/v1/resume", post_resume, methods=["POST"]),
        Route("/v1/artifacts/{path:path}", get_artifacts, methods=["GET"]),
    ]
    app.router.routes = routes
    return app
