# 03 — Campaign (phased handoff)

Teaches a two-phase campaign: pick a winner by metric, hand off **params** and a **pinned file**, and continue in a later phase.

Domain cells live in [`project/`](../project/) (`cell1a`…`cell2b`). `run.py` maps `(phase_id, cell_id)` → those modules and wraps `Run` I/O.

Indexing convention used here:

| Layer | Pattern | Examples |
|---|---|---|
| Matrix | `phase<phase_id>` | `phase1`, `phase2` |
| Run | `cell<phase_id><ablation_id>` | `cell1a`, `cell1b`, `cell2a`, `cell2b` |
| Matrix cell id | ablation letter only | `a`, `b` |

## Files

| Path | Role |
|---|---|
| `run.py` | Campaign entrypoint; `CELLS[(phase, cell_id)]` → project module |
| `../project/cell1a.py` … `cell2b.py` | Plain per-cell compute + weights |
| `configs/run/cell1a.toml` … `cell2b.toml` | Per-cell run configs (`phase` in `fingerprint_keys`) |
| `configs/matrix/phase1.toml` / `phase2.toml` | Per-phase matrices |
| `configs/campaign/phased.toml` | Phases, winner metric, `handoff_keys` |

## Handoff

1. **Params** — phase `handoff_keys = ["mode"]` copies the winner’s `mode` into cumulative `handoff.json` (handoff wins over later cell defaults).
2. **Files** — phase 1 wrapper `pin_artifact("model", …)` on a stem listed in `[run].handoff_artifacts`; the campaign copies it to `campaign_dir/handoff/<phase_id>/…`. Phase 2 runs see it as `run.handoff_artifacts["model"]` (local path under the run’s `handoff/`).

## Run

```bash
cd examples/03_campaign
python run.py --config phased.toml
```

## What to inspect

Under `results/campaign/<stamp>_phased/`:

- `winners.json` — winning cell per phase (`mode=x` / cell `a` should win phase 1)
- `handoff.json` — cumulative `params` + `artifacts` paths under `handoff/`
- `handoff/1/model.bin` — file promoted from the phase-1 winner
- phase matrix dirs nested via the campaign ledger (`…_phase1`, `…_phase2`)

Phase 2 cells receive `mode` from handoff and the pinned model file. `params.phase` is in `fingerprint_keys` so phase 2 does not reuse phase 1 run packages when the phase body differs.

## Docs

[Lifecycle — Handoff](../../docs/lifecycle.md) · [Config — Campaign](../../docs/config.md#campaign)
