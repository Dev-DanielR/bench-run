# 02 — Matrix (ablation)

Teaches a two-cell matrix with repeats: fingerprint reuse, `stats.json`, `compare.json`, and figures.

## Files

| Path | Role |
|---|---|
| `run.py` | Maps `cell_id` `on`/`off` → [`project.on`](../project/on.py) / [`project.off`](../project/off.py) |
| `../project/on.py` / `off.py` | Plain cells (scores + mode string) |
| `configs/run/on.toml` | Cell “on” run config |
| `configs/run/off.toml` | Cell “off” run config |
| `configs/matrix/factor_a.toml` | Cells, repeats, baseline, figure metrics |

## Run

```bash
cd examples/02_matrix
python run.py --config factor_a.toml
```

## What to inspect

Under `results/matrix/<stamp>_factor_a/`:

- `manifest.json` — per-cell status and completed run ids
- `stats.json` — mean±std of `accuracy` per cell (`n` = repeats)
- `compare.json` — ablation vs `baseline_cell`
- `figures/accuracy.png` — bar chart (requires `bench-run[figures]`)
- nested run dirs under the ledger’s run results for each repeat

Re-run the same command: completed fingerprints are reused when params match.

## Docs

[Concepts](../../docs/concepts.md) · [Config — Matrix](../../docs/config.md#matrix) · [Artifacts](../../docs/artifacts.md)
