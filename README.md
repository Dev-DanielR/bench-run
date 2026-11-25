# bench-run

TOML-driven experiment orchestration: single runs, ablation matrices with fingerprint reuse and mean±std figures, phased campaigns with winner hand-off, and an optional coordinator for distributed execution.

- Reproducible run directories (config snapshot, log, metrics, outputs)
- Multi-cell matrices with repeats, fingerprint reuse, stats, compare, and charts
- Multi-phase campaigns that pin winning knobs into later phases
- Preflight on every Run before launch; resume after cancel or fail
- Optional coordinator drives matrices/campaigns; workers claim single Runs, run locally, and push to one ledger

## Install

Core (local Run / Matrix / Campaign; no charts, no distributed):

```bash
pip install "bench-run @ git+https://github.com/Dev-DanielR/bench-run.git"
```

Extras:

| Extra | Adds | Needed for |
|---|---|---|
| `figures` | matplotlib | Matrix PNG charts |
| `coord` | httpx, starlette, uvicorn, python-multipart | `--role coordinator` / `--role worker` |
| `dev` | pytest + both extras | Contributors / full test suite |

```bash
pip install "bench-run[figures] @ git+https://github.com/Dev-DanielR/bench-run.git"
pip install "bench-run[figures,coord] @ git+https://github.com/Dev-DanielR/bench-run.git"
```

From a clone:

```bash
pip install -e ".[dev]"
```

## Use as a sidecar

bench-run is a side harness next to your app. Product CLIs, web servers, and scripts stay separate; the sidecar only wraps app code for experiments.

Recommended layout (hidden sidecar under the app root):

```text
my_app/
  myapp/                      # your library / domain
  cli.py | web/ | …           # product entrypoints
  .bench-run/                 # experiment sidecar (auto-discovered)
    run.py                    # thin wrapper → main(runner)
    configs/
      run/baseline.toml
    results/                  # created at runtime
```

Workspace root resolution:

1. `BENCH_RUN_ROOT` if set
2. else `cwd/.bench-run` when that directory exists
3. else `cwd`

So from `my_app/` you can run without exporting the env var:

```bash
cd my_app
python .bench-run/run.py --config baseline.toml
```

```python
# .bench-run/run.py
from bench_run import Run, main
from myapp import baseline  # your code

def runner(run: Run) -> None:
    accuracy = baseline.run(seed=int(run.params.get("seed", 0)))
    run.add_metric("accuracy", accuracy)

if __name__ == "__main__":
    raise SystemExit(main(runner))
```

```toml
# .bench-run/configs/run/baseline.toml
[run]
name = "baseline"

[params]
seed = 0
```

```bash
python .bench-run/run.py --config factor_a.toml          # needs figures extra for PNGs
python .bench-run/run.py --resume results/matrix/<stamp>_factor_a
python .bench-run/run.py --role coordinator --config lab.toml --config factor_a.toml   # needs coord
python .bench-run/run.py --role worker --config lab.toml
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

## Examples

In-repo demos use a **flat** workspace (example folder = root: `configs/`, `results/`), not `.bench-run/`:

```bash
pip install -e ".[dev]"
cd examples/01_run
python run.py --config baseline.toml
```

Walk through [`examples/`](examples/) (run → matrix → campaign → failure modes → halt/resume → distributed).

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
