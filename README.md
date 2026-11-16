# bench-run

TOML-driven experiment orchestration: single runs, ablation matrices with fingerprint reuse and mean±std figures, phased campaigns with winner hand-off, and an optional coordinator for distributed execution.

- Reproducible run directories (config snapshot, log, metrics, outputs)
- Multi-cell matrices with repeats, fingerprint reuse, stats, compare, and charts
- Multi-phase campaigns that pin winning knobs into later phases
- Preflight on every Run before launch; resume after cancel or fail
- Optional coordinator drives matrices/campaigns; workers claim single Runs, run locally, and push to one ledger

## Get started

```python
# my_bench.py
from bench_run import Run, MatrixRun, CampaignRun, main

def runner(run: Run) -> None:
    # your experiment body
    run.addMetric("accuracy", 0.8)

if __name__ == "__main__":
    raise SystemExit(main(runner))
```

```bash
# Local matrix (configs under bench_run/configs/matrix/)
python my_bench.py --config factor_a.toml

# Resume
python my_bench.py --resume bench_run/results/campaign/20250101_120000_phased

# Distributed: coordinator drives EXP; workers only claim Runs
python my_bench.py --role coordinator --config lab.toml --config phased.toml
python my_bench.py --role worker --config lab.toml
```

Or drive layers in code (local):

```python
with Run("baseline.toml") as run:
    run.preflight()
    runner(run)

with MatrixRun("factor_a.toml") as matrix:
    matrix.execute(runner)

with CampaignRun("phased.toml") as campaign:
    campaign.execute(runner)
```

## Docs

| Doc | Contents |
|---|---|
| [Concepts](docs/concepts.md) | Hierarchy, runner contract, ledger injection, behavior |
| [Layout](docs/layout.md) | On-disk layout, artifact overview |
| [Artifacts](docs/artifacts.md) | JSON schemas, status enums, figures naming |
| [Lifecycle](docs/lifecycle.md) | Preflight, execute/resume, fingerprint, handoff |
| [Ledger](docs/ledger.md) | Protocol, run package, REST, claims, aggregation |
| [Config](docs/config.md) | Run / matrix / campaign TOML schemas |
| [API](docs/api.md) | Public symbols and usage |
| [CLI](docs/cli.md) | Argv, roles, examples |
| [Execution](docs/execution.md) | Coordinator + workers overview |
| [Package](docs/package.md) | Module layout and dependencies |
| [Limitations](docs/limitations.md) | Limits and roadmap |
