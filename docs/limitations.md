# Limitations and roadmap

## Limitations

- Campaign handoff pins params and declared artifact stems/keys; it does not pass arbitrary intermediate stage artifact graphs between phases.
- Distributed execution requires explicit `--role coordinator` or `--role worker`; there is no implicit network use.
- In distributed mode only the coordinator drives `MatrixRun` / `CampaignRun`; workers execute claimed `Run`s only.
- Entry is a project script that calls `main(runner)`; there is no standalone package console script that supplies a runner.
- Coordinator runs a single uvicorn worker process so the in-process driver and FS store stay coherent.
- Figures require `matplotlib`; absence logs a warning and skips PNGs.

## Roadmap

- Execution auth beyond shared bearer token; multi-tenant isolation
- Richer dispatch policies (priorities, resource tags)
- Richer cross-phase artifact hand-off (stage outputs beyond param/stem pins)
- Optional `--runner pkg.mod:fn` import path for a standalone `bench-run` console script

## Implementation checklist (v1 one-shot)

Ordered PRs / slices. Each slice is independently reviewable; later slices depend on earlier ones.

### PR1 — Skeleton + config + fingerprint

| Item | Detail |
|---|---|
| Files | `bench_run/{__init__,config,fingerprint}.py`, `pyproject.toml` |
| Deliver | Package imports; TOML load/classify; `resolve*ConfigPath`; workspace root; canonical fingerprint sha256; write config snapshots via `tomli-w` |
| Deps | `tomli-w` |
| Test | Classify fixtures; fingerprint golden vectors (sorted keys, bool, overlay params) |

### PR2 — LocalFsLedger + Run

| Item | Detail |
|---|---|
| Files | `bench_run/run.py`, `bench_run/ledger/{base,local}.py`, `artifacts.py` (metadata/metrics IO) |
| Deliver | `Ledger` protocol methods used by Run; `Run` context manager; preflight; metrics/items; `output/`/`pinArtifact`; complete/fail/cancel; stamp dirs |
| Test | Temp dir Run happy path + preflight cancel + `__exit__` finalize |

### PR3 — MatrixRun local

| Item | Detail |
|---|---|
| Files | `matrix.py`, stats/compare in `artifacts.py`, `figures.py` |
| Deliver | Reuse scan, shortfall, `max_failures`, cell status, `stats.json`/`compare.json`, figures Agg, `execute`/`resume`/`compare` |
| Test | 2-cell matrix repeats=2 with reuse; failure cap marks cell failed; figures smoke |

### PR4 — CampaignRun local

| Item | Detail |
|---|---|
| Files | `campaign.py` |
| Deliver | Phase loop, `selectWinner`, handoff params + file copy under `handoff/<phase_id>/`, `continue_on_fail`, preflight-cancel halt, resume restores handoff |
| Test | 2-phase campaign with handoff key merge and artifact file presence |

### PR5 — CLI `main` local paths

| Item | Detail |
|---|---|
| Files | `main.py` |
| Deliver | Argv parse, classification, arity, exit codes, `--resume`, cell/phase filters |
| Test | CLI argv table (local matrix, bad arity → 1) |

### PR6 — Coordinator server + REST

| Item | Detail |
|---|---|
| Files | `server/{app,claims,store,aggregate}.py` |
| Deliver | Starlette app; store under `data_dir`; claims/leases; package multipart PUT; fingerprints; matrices/campaigns submit; resume; auth bearer; aggregation hooks |
| Deps | `starlette`, `uvicorn` |
| Test | httpx ASGI transport: claim → package → manifest update |

### PR7 — CoordinatorLedger + worker loop

| Item | Detail |
|---|---|
| Files | `ledger/coordinator.py`, `worker.py`; wire `main` roles |
| Deliver | HTTP client ledger; claim loop; heartbeat; handoff download; push package; coordinator drives Matrix/Campaign in-server |
| Deps | `httpx` |
| Test | Local integration: coordinator+worker threads against 1-cell matrix |

### PR8 — Docs polish + package export

| Item | Detail |
|---|---|
| Files | README exports, `__init__` public API, optional example `my_bench.py` in repo if desired |
| Deliver | Versioned deps in `pyproject.toml`; confirm docs match code |

## Acceptance (v1 done)

1. Local: `Run` / `MatrixRun` / `CampaignRun` execute + resume per docs.
2. Fingerprint reuse fills repeats without re-running.
3. Campaign handoff params + files visible to phase-2 runner via `run.handoff_artifacts`.
4. Distributed: coordinator+worker complete the same matrix; stats/compare appear on coordinator store.
5. Preflight cancel never proceeds to winner/handoff; `continue_on_fail` does not override it.
6. Exit codes match [CLI](cli.md).
