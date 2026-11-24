# 04 — Resume

Teaches `--resume` on an incomplete matrix: shortfall repeats finish without redoing completed work.

## Files

| Path | Role |
|---|---|
| `run.py` | Entrypoint for both the full run and resume |
| `seed_partial.py` | Leaves a matrix with `repeats=2` but only one complete per cell |
| `bench_run/configs/run/*.toml` | Cell configs |
| `bench_run/configs/matrix/factor_a.toml` | Target matrix (`repeats = 2`) |

## Run

```bash
cd examples/04_resume

# 1) Create an incomplete matrix dir (prints the path)
python seed_partial.py

# 2) Resume — fills shortfall to repeats=2
python run.py --resume bench_run/results/matrix/<stamp>_factor_a
```

Use the path printed by `seed_partial.py` (or list `bench_run/results/matrix/`).

## What to inspect

After seed:

- `manifest.json` — each cell has one `completed_run_ids` entry; matrix `status` is `running`
- `metadata.json` — `status: running`

After resume:

- each cell has two completed runs; matrix `status: complete`
- `stats.json` with `n == 2`

## Docs

[Lifecycle — Resume](../../docs/lifecycle.md) · [CLI](../../docs/cli.md)
