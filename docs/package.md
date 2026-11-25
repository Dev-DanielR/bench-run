# Package layout

Python package name: `bench_run`.

```
bench_run/
  __init__.py          # exports: Run, MatrixRun, CampaignRun, main, PreflightCancel, resolve_*_config_path
  main.py              # argv parse → resolve configs → execution runners
  config.py            # TOML load, path resolve, classify experiment vs execution
  fingerprint.py       # canonical payload + sha256
  fs.py                # JSON IO, stamps, metadata/metrics/manifest helpers
  layers/
    __init__.py        # re-exports Run, MatrixRun, CampaignRun, PreflightCancel
    run.py             # Run context manager, metrics helpers, preflight, pins
    matrix.py          # MatrixRun: shortfall, stats, compare, figures drive
    campaign.py        # CampaignRun: phases, select_winner, handoff
  reporting/
    __init__.py
    stats.py           # build_stats
    compare.py         # build_compare
    figures.py         # matplotlib Agg mean±std bar charts
    matrix.py          # write_matrix_reports / rewrite_compare_and_figures
  execution/
    __init__.py
    local.py           # local drive + resume
    worker.py          # claim loop + worker role entry
    server/            # coordinator only
      __init__.py
      coordinator.py   # serve + optional matrix/campaign drive
      app.py           # Starlette app
      claims.py        # Run work queue / leases
      aggregate.py     # cell terminal/status; calls reporting
      store.py         # coordinator persistent store
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
```

| Module | Responsibility |
|---|---|
| `layers/run.py` | Single-run lifecycle, metrics, pins, preflight |
| `layers/matrix.py` | Cell shortfall orchestration; delegates reports to `reporting/` |
| `layers/campaign.py` | Phase loop, winner selection, handoff merge |
| `main.py` | CLI entry: argv + config resolve + dispatch |
| `execution/local.py` | Local run/matrix/campaign drive and resume |
| `execution/worker.py` | Worker claim/heartbeat/push loop |
| `execution/server/` | Coordinator HTTP store + in-process driver |
| `fs.py` | On-disk JSON / stamp / metadata helpers |
| `reporting/` | stats, compare, figures |
| `config.py` | Load/validate TOML; resolve config paths |
| `fingerprint.py` | Canonical JSON fingerprint + sha256 |
| `ledger/` | Orchestration: claims, outputs, manifests, stats, packages |
| `sink/` | Telemetry: log, progress, metrics |

| `ledger.base` | Ledger protocol |
| `ledger.local` | Local filesystem ledger |
| `ledger.coordinator` | HTTP client ledger for workers |
| `execution.server.app` | Starlette + uvicorn ASGI app |
| `execution.server.claims` | Claim queue and leases |
| `execution.server.aggregate` | Cell status; triggers reporting |
| `execution.server.store` | Coordinator persistent store |

Project workspace layout (data + configs) remains the on-disk tree in [Layout](layout.md); it is not necessarily inside the import package.

## Public exports

```python
from bench_run import (
    Run,
    MatrixRun,
    CampaignRun,
    main,
    PreflightCancel,
    resolve_config_path,
    resolve_matrix_config_path,
    resolve_campaign_config_path,
)
```

Advanced (optional, documented for programmatic DI):

```python
from bench_run.ledger import LocalFsLedger, CoordinatorLedger
```

## Dependencies

| Dep | Extra | Use |
|---|---|---|
| Python 3.11+ | (core) | `tomllib`, typing |
| `tomli-w` | (core) | Writing config snapshots |
| `alive-progress` | (core) | Optional TTY progress bars |
| `matplotlib` | `figures` | Matrix figures (Agg); missing → `ImportError` with install hint |
| `httpx` | `coord` | `CoordinatorLedger` HTTP client |
| `starlette` | `coord` | Coordinator HTTP app |
| `uvicorn` | `coord` | ASGI server; **workers=1** (in-process matrix/campaign driver) |
| `python-multipart` | `coord` | Coordinator package upload |

No YAML library. TOML read via stdlib `tomllib`; write via `tomli-w`.

Install from git (PyPI pending):

```bash
pip install "bench-run[figures,coord] @ git+https://github.com/Dev-DanielR/bench-run.git"
```

### pyproject deps sketch

```toml
[project]
requires-python = ">=3.11"
dependencies = ["tomli-w", "alive-progress"]

[project.optional-dependencies]
figures = ["matplotlib"]
coord = ["httpx", "starlette", "uvicorn", "python-multipart"]
dev = ["pytest", "matplotlib", "httpx", "starlette", "uvicorn", "python-multipart"]
```

## Entry

No console script in v1. Projects ship `my_bench.py` that calls `main(runner)`.

Coordinator serve uses uvicorn with a single worker so the in-process matrix/campaign driver shares memory with the HTTP app.
