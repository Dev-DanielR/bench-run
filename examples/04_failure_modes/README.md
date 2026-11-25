# 04 — Failure modes

Teaches two distinct terminal paths for a matrix cell:

| Mode | How it happens | Cell status | Runner |
|---|---|---|---|
| **Preflight cancel** | `[data].root` points at a missing path | `cancelled` | Never called |
| **Runtime fail** | Runner raises; failures hit `max_failures` | `failed` | Called (and retried) |

The sibling healthy cell still finishes `ok` in both matrices. Matrix orchestration always continues other cells.

## Files

| Path | Role |
|---|---|
| `run.py` | Maps `cell_id` → [`project.ok`](../project/ok.py) / [`project.boom`](../project/boom.py) |
| `../project/ok.py` | Healthy cell |
| `../project/boom.py` | Raises when `fail=true` (default) |
| `configs/run/ok.toml` | Healthy run config |
| `configs/run/missing_data.toml` | `[data].root` → nonexistent path |
| `configs/run/boom.toml` | Boom run config (no data root) |
| `configs/matrix/one_cancel.toml` | Cells `cancel` + `ok` |
| `configs/matrix/one_fail.toml` | Cells `boom` + `ok` (`repeats=2`, `max_failures=2`) |

## Run — preflight cancel

```bash
cd examples/04_failure_modes
python run.py --config one_cancel.toml
```

Process exit is **0** here because a sibling cell is `ok` (CLI only maps to 3/2 when every cell is cancelled/failed). Read the manifest either way.

Under `results/matrix/<stamp>_one_cancel/`:

- `manifest.json` — cell `cancel` status `cancelled`; cell `ok` status `ok`
- `cancelled_run_ids` on the cancel cell; no `metrics.json` from that run (preflight never launched the runner)

## Run — runtime fail

```bash
python run.py --config one_fail.toml
```

Same exit-code rule: **0** while `ok` succeeds beside `boom`.

Under `results/matrix/<stamp>_one_fail/`:

- `manifest.json` — cell `boom` status `failed` with `len(failed_run_ids) >= 2` and empty `completed_run_ids`
- cell `ok` status `ok` with two completed repeats

## Programmatic hook (optional)

`main(runner)` does not take a hook; for custom checks use the API:

```python
from bench_run import PreflightCancel, Run

def hook(run: Run):
    if run.params.get("skip"):
        raise PreflightCancel("skipped by hook")

with Run("ok.toml", preflight_hook=hook) as run:
    run.preflight()
    runner(run)
```

## Docs

[Lifecycle — Preflight](../../docs/lifecycle.md) · [Failure / retry policy](../../docs/lifecycle.md#failure--retry-policy) · [Concepts](../../docs/concepts.md) · [CLI exit codes](../../docs/cli.md#exit-codes)
