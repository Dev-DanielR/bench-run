# Layout and artifacts

```
bench_run/
  configs/
    {run,matrix,campaign}/                    # experiment definition
    execution/                                # coordinator + worker (optional)
  results/{run,matrix,campaign}/<stamp>_<stem>/
  data/<dataset>/{raw,artifacts}/             # persistent; from [data].root
  benchmarks/                                 # fixtures: inputs, questions, expected answers, …
```

Experiment TOMLs describe **what** to run. Execution TOMLs describe **where/how** work is scheduled. Execution configs are read only when `--role` is set (see [CLI](cli.md)).

**Formats:** config is always TOML. Structured artifacts are JSON. Logs are plain text.

## Shared core

Every `results/{run,matrix,campaign}/<stamp>_<stem>/` dir:

| File | Format | Role |
|---|---|---|
| `config.toml` | TOML | Snapshot of the config that launched this dir |
| `metadata.json` | JSON | id, status, timestamps, paths, config stem |
| `log.txt` | text | UTC log stream |

## Layer-specific artifacts

| Layer | Extra artifacts |
|---|---|
| **Run** | `metrics.json`, `output/`, optional `handoff/` (materialized pins for this Run) |
| **Matrix** | `manifest.json`, `stats.json`, `compare.json`, `figures/` |
| **Campaign** | `manifest.json`, `winners.json`, `handoff.json`, `handoff/<phase_id>/` (copied pin files) |

`manifest.json` is the execution ledger at matrix and campaign levels (cells vs phases). A Run has no manifest; `metrics.json` and `metadata.json` cover that role.

## Result directory naming

Pattern: `<stamp>_<stem>` where `stamp = UTC strftime %Y%m%d_%H%M%S` and `stem` is `--name` or config `name` or config filename stem. If the directory exists, append `_2`, `_3`, … before create.

Coordinator server store (`coordinator.data_dir`) mirrors the same `results/{run,matrix,campaign}/…` layout plus a `claims.json` (or equivalent) for the work queue.

## Workspace root

`BENCH_RUN_ROOT` environment variable if set, otherwise process cwd. The tree `bench_run/` is resolved under that root.

Exact JSON shapes, status enums, and figure filenames: [Artifacts](artifacts.md).

## metrics.json vs stats.json vs compare.json

| File | Layer | Role |
|---|---|---|
| `metrics.json` | Run | One experiment’s values (`run` scalars + optional `items`), written by the runner |
| `stats.json` | Matrix | Per-cell aggregates (mean±std of run-level scalars across repeats) |
| `compare.json` | Matrix | Cross-cell comparison derived from `stats.json` |

Flow: each Run writes `metrics.json` → matrix aggregates into `stats.json` → builds `compare.json` → writes figures. Locally the in-process driver does this under `results/`. In distributed mode workers push run packages; the **coordinator** driver aggregates matrix stats/compare/figures. `MatrixRun.compare()` rebuilds compare and figures from existing stats (local ledger).

- `addMetric` → `run`; `addItemMetric` / `addItemMetrics` → `items`
- Winner selection and charts read **run-level** numeric scalars (mean±std across repeats)
- Fingerprints: [Lifecycle — Fingerprint](lifecycle.md#fingerprint)
