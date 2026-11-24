# 06 — Preflight cancel

Teaches that preflight runs on the executing machine before `runner`, and a cancel is distinct from a soft cell failure.

This demo uses the **structural** check: `[data].root` must exist when set. One matrix cell points at a missing dataset path; the other cell is fine.

## Files

| Path | Role |
|---|---|
| `run.py` | Normal runner (never called for the bad cell) |
| `bench_run/configs/run/ok.toml` | Healthy run config |
| `bench_run/configs/run/missing_data.toml` | `[data].root` → nonexistent path |
| `bench_run/configs/matrix/one_bad.toml` | Two cells: `bad` + `good` |

## Run

```bash
cd examples/06_preflight_cancel
python run.py --config one_bad.toml
```

Expect a non-zero exit if the matrix layer ends cancelled/failed per halt rules; inspect the manifest either way.

## What to inspect

Under `bench_run/results/matrix/<stamp>_one_bad/`:

- `manifest.json` — cell `bad` status `cancelled`; cell `good` status `ok`
- No `metrics.json` from the cancelled cell’s runner (preflight never launched it)

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

[Lifecycle — Preflight](../../docs/lifecycle.md) · [Concepts](../../docs/concepts.md)
