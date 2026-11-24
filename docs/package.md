# Package layout

Python package name: `bench_run`.

```
bench_run/
  __init__.py          # exports: Run, MatrixRun, CampaignRun, main, PreflightCancel, resolve*ConfigPath
  run.py               # Run context manager, metrics helpers, preflight, pins
  matrix.py            # MatrixRun: shortfall, stats, compare, figures drive
  campaign.py          # CampaignRun: phases, select_winner, handoff
  main.py              # argv parse → local drive | coordinator serve(+drive) | worker claim loop
  config.py            # TOML load, path resolve, classify experiment vs execution
  fingerprint.py       # canonical payload + sha256
  artifacts.py         # read/write metadata, metrics, manifests, stats, compare, handoff
  figures.py           # matplotlib Agg mean±std bar charts
  worker.py            # claim_run loop: RunSpec → preflight → runner → push
  ledger/
    __init__.py
    base.py            # Ledger Protocol (orchestration)
    local.py           # LocalFsLedger (filesystem)
    coordinator.py     # CoordinatorLedger HTTP client (httpx)
  sink/
    __init__.py
    base.py            # Sink Protocol + Scope/events (telemetry)
    local.py           # LocalFsSink
    coordinator.py     # CoordinatorSink (worker buffer)
  server/              # coordinator only
    __init__.py
    app.py             # Starlette app + hosts MatrixRun/CampaignRun driver
    claims.py          # Run work queue / leases
    aggregate.py       # matrix stats/compare/figures from run packages
    store.py           # server-side ledger store
```

| Module | Responsibility |
|---|---|
| `run.py` | Single-run lifecycle, metrics, pins, preflight |
| `matrix.py` | Cell shortfall orchestration, stats/compare/figures |
| `campaign.py` | Phase loop, winner selection, handoff merge |
| `main.py` | CLI entry: role dispatch |
| `config.py` | Load/validate TOML; resolve config paths |
| `fingerprint.py` | Canonical JSON fingerprint + sha256 |
| `artifacts.py` | On-disk JSON artifact IO |
| `figures.py` | Best-effort matplotlib Agg charts |
| `worker.py` | Worker claim/heartbeat/push loop |
| `ledger/` | Orchestration: claims, outputs, manifests, stats, packages |
| `sink/` | Telemetry: log, progress, metrics |

| `ledger.base` | Ledger protocol |
| `ledger.local` | Local filesystem ledger |
| `ledger.coordinator` | HTTP client ledger for workers |
| `server.app` | Starlette + uvicorn ASGI app; in-process driver |
| `server.claims` | Claim queue and leases |
| `server.aggregate` | Package → stats/compare/figures |
| `server.store` | Coordinator persistent store |

Project workspace layout (data + configs) remains the on-disk tree in [Layout](layout.md); it is not necessarily inside the import package.

## Public exports

```python
from bench_run import (
    Run,
    MatrixRun,
    CampaignRun,
    main,
    PreflightCancel,
    resolveConfigPath,
    resolveMatrixConfigPath,
    resolveCampaignConfigPath,
)
```

Advanced (optional, documented for programmatic DI):

```python
from bench_run.ledger import LocalFsLedger, CoordinatorLedger
```

## Dependencies

| Dep | Use |
|---|---|
| Python 3.11+ | `tomllib`, typing |
| `matplotlib` | matrix figures (Agg); import deferred; missing → warn and skip figures |
| `httpx` | `CoordinatorLedger` HTTP client (explicit dep) |
| `starlette` | Coordinator HTTP app |
| `uvicorn` | ASGI server; **workers=1** (single process — MatrixRun/CampaignRun driver is in-process) |
| `tomli-w` | Writing config snapshots |

No YAML library. TOML read via stdlib `tomllib`; write via `tomli-w`.

### pyproject deps sketch

```toml
[project]
requires-python = ">=3.11"
dependencies = [
  "matplotlib",
  "httpx",
  "starlette",
  "uvicorn",
  "tomli-w",
]
```

## Entry

No console script in v1. Projects ship `my_bench.py` that calls `main(runner)`.

Coordinator serve uses uvicorn with a single worker so the in-process matrix/campaign driver shares memory with the HTTP app.
