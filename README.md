# bench-run

TOML-driven experiment orchestration: single runs, ablation matrices with fingerprint reuse and mean±std figures, phased campaigns with winner hand-off, and an optional coordinator for distributed execution.

- Reproducible run directories (config snapshot, log, metrics, outputs)
- Multi-cell matrices with repeats, fingerprint reuse, stats, compare, and charts
- Multi-phase campaigns that pin winning knobs into later phases
- Preflight on every Run before launch; resume after cancel or fail
- Optional coordinator drives matrices/campaigns; workers claim single Runs, run locally, and push to one ledger

## Get started

Walk through the self-contained demos under [`examples/`](examples/) (run → matrix → campaign → preflight → resume → distributed). Each folder sets `BENCH_RUN_ROOT` so configs and results stay local to that example.

```bash
pip install -e .
cd examples/01_run
python run.py --config baseline.toml
```

Minimal project shape:

```python
# run.py
from bench_run import Run, main

def runner(run: Run) -> None:
    run.add_metric("accuracy", 0.8)

if __name__ == "__main__":
    raise SystemExit(main(runner))
```

```bash
python run.py --config factor_a.toml
python run.py --resume bench_run/results/matrix/<stamp>_factor_a
python run.py --role coordinator --config lab.toml --config factor_a.toml
python run.py --role worker --config lab.toml
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
| [Ledger](docs/ledger.md) | Orchestration protocol, run package, REST, claims |
| [Sink](docs/sink.md) | Telemetry: log, progress, metrics |
| [Config](docs/config.md) | Run / matrix / campaign TOML schemas |
| [API](docs/api.md) | Public symbols and usage |
| [CLI](docs/cli.md) | Argv, roles, examples |
| [Execution](docs/execution.md) | Coordinator + workers overview |
| [Package](docs/package.md) | Module layout and dependencies |
| [Limitations](docs/limitations.md) | Limits and roadmap |
