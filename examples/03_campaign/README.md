# 03 — Campaign (phased handoff)

Teaches a two-phase campaign: pick a winner by metric, copy `handoff_keys` into later phases, and pin an artifact.

## Files

| Path | Role |
|---|---|
| `run.py` | Scores by `mode_a`; pins `model.bin` |
| `bench_run/configs/run/cell_a.toml` / `cell_b.toml` | Phase cell run configs |
| `bench_run/configs/matrix/stage1.toml` / `stage2.toml` | Per-phase matrices |
| `bench_run/configs/campaign/phased.toml` | Phases, winner metric, handoff keys |

## Run

```bash
cd examples/03_campaign
python run.py --config phased.toml
```

## What to inspect

Under `bench_run/results/campaign/<stamp>_phased/`:

- `winners.json` — winning cell per phase (`mode_a=x` should win phase 1)
- `handoff.json` — cumulative params + pinned artifact paths under `handoff/`
- phase matrix dirs nested via the campaign ledger

Phase 2 cells receive `mode_a` from handoff (winner wins over the child run defaults).

## Docs

[Lifecycle — Handoff](../../docs/lifecycle.md) · [Config — Campaign](../../docs/config.md#campaign)
