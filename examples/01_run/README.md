# 01 — Single Run

Teaches the smallest useful project: attach a `runner`, call `main(runner)`, drive one TOML config.

## Files

| Path | Role |
|---|---|
| `run.py` | Entrypoint; wraps [`project.baseline`](../project/baseline.py) |
| `../project/baseline.py` | Plain cell: score + note text |
| `bench_run/configs/run/baseline.toml` | Experiment knobs under `[run]` / `[params]` |

## Run

```bash
cd examples/01_run
python run.py --config baseline.toml
```

## What to inspect

Under `bench_run/results/run/<stamp>_baseline/`:

- `config.toml` — snapshot of the experiment config
- `metadata.json` — id, status, timestamps
- `metrics.json` — `accuracy` from the runner
- `output/note.txt` — file written via `output_path`
- `log.txt` — run log

## Docs

[API](../../docs/api.md) · [Config — Run](../../docs/config.md#run) · [CLI](../../docs/cli.md)
