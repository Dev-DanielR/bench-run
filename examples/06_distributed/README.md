# 06 — Distributed (coordinator + worker)

Teaches the same matrix as local mode, driven by a coordinator while a worker claims individual Runs. The **runner body is unchanged** (same `project.on` / `project.off` wrap as [02_matrix](../02_matrix/)).

## Files

| Path | Role |
|---|---|
| `run.py` | Maps `cell_id` → [`project.on`](../project/on.py) / [`project.off`](../project/off.py) |
| `../project/on.py` / `off.py` | Plain cells shared with example 02 |
| `bench_run/configs/run/on.toml` / `off.toml` | Cell configs |
| `bench_run/configs/matrix/factor_a.toml` | Experiment matrix |
| `bench_run/configs/execution/lab.toml` | `[coordinator]` + `[worker]` on localhost |

## Run (two terminals)

```bash
cd examples/06_distributed

# Terminal 1 — ledger + drive the matrix; exits when the matrix is terminal
python run.py --role coordinator --config lab.toml --config factor_a.toml --until-done

# Terminal 2 — claim loop; exits after idle empty polls (or if coordinator goes down)
python run.py --role worker --config lab.toml --until-done
```

Omit `--until-done` to keep the old forever-serve / forever-claim behavior (Ctrl+C to stop).

## What to inspect

- Coordinator store under `bench_run/results/_coordinator/` (runs, matrices, manifests, stats, figures)
- Matrix `log.txt` under `_coordinator/matrices/<id>/` for progress status lines
- Worker never runs `MatrixRun.execute`; it only claims `RunSpec`s

## Notes

- `lab.toml` binds `127.0.0.1:8765` with no auth (open). Change the port if busy.
- Same `--config factor_a.toml` locally (omit `--role`) is the zero-network path.

## Docs

[Execution](../../docs/execution.md) · [CLI](../../docs/cli.md) · [Ledger](../../docs/ledger.md)
