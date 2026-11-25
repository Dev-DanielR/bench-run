# 05 — Halt + resume / continue_on_fail

Teaches campaign **fail halt** (`continue_on_fail = false`) with **`--resume`**, and the contrast **`continue_on_fail = true`** (failed phase skipped; later phases still run).

Halt path: phase 1 stops failed when a boom cell raises; after clearing `params.fail`, resume re-drives phase 1 (reuses completed siblings), writes handoff, then runs phase 2.

Same `(phase_id, cell_id)` → `project` dispatch as [03_campaign](../03_campaign/), plus a phase-1 `boom` cell gated by [`project.boom`](../project/boom.py).

Indexing convention:

| Layer | Pattern | Examples |
|---|---|---|
| Matrix | `phase<phase_id>` | `phase1`, `phase2` |
| Run | `cell<phase_id><ablation_id>` | `cell1a`, `cell1b`, `boom`, `cell2a`, `cell2b` |
| Matrix cell id | ablation id | `a`, `b`, `boom` |

## Files

| Path | Role |
|---|---|
| `run.py` | Entrypoint for halt run and `--resume` |
| `seed_halt.py` | Runs until fail halt, then sets boom `fail=false` |
| `../project/cell1a.py` … `cell2b.py` | Shared plain cells |
| `../project/boom.py` | Raises when `fail=true`; scores 0.4 when `fail=false` |
| `configs/run/boom.toml` | Boom run config (`fingerprint_keys` include `fail`) |
| `configs/matrix/phase1.toml` | Phase 1: `a`, `b`, `boom` (`fail` in cell params) |
| `configs/campaign/phased.toml` | Two-phase campaign, `continue_on_fail = false` |
| `configs/campaign/continue_on.toml` | Same phases, `continue_on_fail = true` |

| Policy | Campaign after boom | Phase 2 | Handoff from phase 1 |
|---|---|---|---|
| `continue_on_fail = false` (`phased.toml`) | `failed` | stays `pending` | none |
| `continue_on_fail = true` (`continue_on.toml`) | `complete` | runs | none (failed phase skips winner/handoff) |

Campaign resume skips `ok` phases and re-enters non-`ok` ones (including `failed`). CLI no-ops only `complete` / `cancelled` campaigns — a **`failed`** campaign is resumable. Each resume of a failed phase opens a **new** child matrix (loads current `phase1.toml` from disk).

## Run — halt + resume

```bash
cd examples/05_halt_resume

# 1) Halt on boom; flip fail=false for the next attempt (prints the path)
python seed_halt.py

# 2) Resume — re-drive phase 1 (a/b reuse), boom succeeds, handoff, phase 2
python run.py --resume results/campaign/<stamp>_phased
```

Use the path printed by `seed_halt.py`.

Manual equivalent: set `fail = true` on the boom cell, `python run.py --config phased.toml` (expect failed campaign), set `fail = false`, then `--resume`.

### What to inspect (halt)

After seed / halt:

- `metadata.json` — `status: failed`
- `manifest.json` — phase 1 `failed`; phase 2 still `pending`
- no phase-1 winner / no `handoff/1/` yet (halt before select_winner)

After resume:

- phase 1 `ok` with `winner_cell` (still `a` at accuracy 0.9)
- `handoff.json` — `mode` + `handoff/1/model.bin`
- phase 2 `ok`; campaign `complete`
- phase 2 outputs chain `weights-phase1-x|weights-phase2`
- boom cell on the **new** phase-1 matrix completed once with `fail=false`

## Run — continue on fail

Leave boom `fail = true`. One shot, no resume:

```bash
cd examples/05_halt_resume
python run.py --config continue_on.toml
```

### What to inspect (continue)

Under `results/campaign/<stamp>_continue_on/`:

- `metadata.json` — `status: complete` (campaign finished despite a failed phase)
- `manifest.json` — phase 1 `failed`; phase 2 `ok`
- no phase-1 winner / no `handoff/1/` (failed phase never selects a winner)
- phase 2 cells run with **default scores** (`no-handoff|weights-phase2` in outputs) because the runner sees an empty handoff — that is expected

Preflight cancel still **halts** the campaign even when `continue_on_fail` is true.

## Docs

[Lifecycle — Resume](../../docs/lifecycle.md#resume) · [Campaign algorithm](../../docs/lifecycle.md#campaign-algorithm-driver) · [CLI](../../docs/cli.md)
