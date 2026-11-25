# Examples

Self-contained demos for **bench-run**. Each folder is its own flat workspace (`configs/`, `results/`): `run.py` sets `BENCH_RUN_ROOT` to that folder via [`_bootstrap.py`](_bootstrap.py).

Domain logic lives in [`project/`](project/) (plain modules, one cell per file, no `bench_run` imports). Each example’s `run.py` imports from `project` and wraps a thin runner for the harness. Bootstrap puts `examples/` on `sys.path` so `import project` works.

```bash
pip install -e ".[dev]"
cd examples/01_run
python run.py --config baseline.toml
```

| Example | Teaches |
|---|---|
| [01_run](01_run/) | Single Run via `main(runner)`, metrics, outputs |
| [02_matrix](02_matrix/) | Ablation grid, repeats, stats / compare / figures |
| [03_campaign](03_campaign/) | Phased campaign, winner selection, param + file handoff |
| [04_failure_modes](04_failure_modes/) | Preflight cancel vs runtime fail (`max_failures`) |
| [05_halt_resume](05_halt_resume/) | Fail halt + resume, and `continue_on_fail=true` contrast |
| [06_distributed](06_distributed/) | Coordinator + worker on localhost |

Suggested order: **01 → 02 → 03 → 04 → 05 → 06**.

Reference docs: [concepts](../docs/concepts.md), [config](../docs/config.md), [cli](../docs/cli.md), [lifecycle](../docs/lifecycle.md), [execution](../docs/execution.md).
