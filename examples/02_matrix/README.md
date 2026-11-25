# 02 — Matrix (ablation)

Teaches a two-cell matrix with repeats: fingerprint reuse, `stats.json`, `compare.json`, and figures.

## Files

| Path | Role |
|---|---|
| `run.py` | Maps `cell_id` `on`/`off` → [`project.on`](../project/on.py) / [`project.off`](../project/off.py) |
| `../project/on.py` / `off.py` | Plain cells (scores + mode string) |
| `bench_run/configs/run/on.toml` | Cell “on” run config |
| `bench_run/configs/run/off.toml` | Cell “off” run config |
| `bench_run/configs/matrix/factor_a.toml` | Cells, repeats, baseline, figure metrics |

## Run

```bash
cd examples/02_matrix
python run.py --config factor_a.toml
```

## What to inspect

Under `bench_run/results/matrix/<stamp>_factor_a/`:

- `manifest.json` — per-cell status and completed run ids
- `stats.json` — mean±std of `accuracy` per cell (`n` = repeats)
- `compare.json` — ablation vs `baseline_cell`
- `figures/accuracy.png` — bar chart (if matplotlib is available)
- nested run dirs under the ledger’s run results for each repeat

Re-run the same command: completed fingerprints are reused when params match.

## Docs

[Concepts](../../docs/concepts.md) · [Config — Matrix](../../docs/config.md#matrix) · [Artifacts](../../docs/artifacts.md)
