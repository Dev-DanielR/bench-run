# Examples

Self-contained demos for **bench-run**. Each folder is its own workspace: `run.py` sets `BENCH_RUN_ROOT` to that folder so configs and results stay under `examples/<name>/bench_run/`.

Entry scripts use [`_bootstrap.py`](_bootstrap.py) so the on-disk `bench_run/` layout tree does not shadow the Python package (repo root is put on `sys.path`).

```bash
pip install -e .   # optional if you run from a checkout; bootstrap also adds the repo root
cd examples/01_run
python run.py --config baseline.toml
```

| Example | Teaches |
|---|---|
| [01_run](01_run/) | Single Run via `main(runner)`, metrics, outputs |
| [02_matrix](02_matrix/) | Ablation grid, repeats, stats / compare / figures |
| [03_campaign](03_campaign/) | Phased campaign, winner selection, handoff params |
| [04_resume](04_resume/) | Incomplete matrix → `--resume` shortfall |
| [05_distributed](05_distributed/) | Coordinator + worker on localhost |
| [06_preflight_cancel](06_preflight_cancel/) | Preflight cancel vs soft failure |

Suggested order: **01 → 02 → 03 → 06 → 04 → 05**.

Reference docs: [concepts](../docs/concepts.md), [config](../docs/config.md), [cli](../docs/cli.md), [lifecycle](../docs/lifecycle.md), [execution](../docs/execution.md).
