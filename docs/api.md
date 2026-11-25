# API

```python
from bench_run import Run, MatrixRun, CampaignRun, main, PreflightCancel

def runner(run: Run) -> None:
    run.add_metric("accuracy", 0.8)

with Run("baseline.toml") as run:
    run.preflight()
    runner(run)

with MatrixRun("factor_a.toml") as matrix:
    matrix.execute(runner)   # discover/reuse → preflight → shortfall → stats/compare → figures

with CampaignRun("phased.toml") as campaign:
    campaign.execute(runner)

# Resume an incomplete campaign directory
CampaignRun.resume("bench_run/results/campaign/<stamp>_phased").execute(runner)

# CLI: local drive, coordinator drive, or worker claim-loop — same runner
if __name__ == "__main__":
    raise SystemExit(main(runner))
```

Workspace root: env `BENCH_RUN_ROOT` else cwd. All relative paths resolve from that root.

## `Run`

### Constructor

```python
Run(
    config: str | Path | dict,
    *,
    name: str | None = None,
    log_to_console: bool = True,
    tty_bar: bool | None = None,
    ledger: Ledger | None = None,
    sink: Sink | None = None,
    preflight_hook: Callable[[Run], bool | None] | None = None,
    parent: dict | None = None,
    params_overlay: dict | None = None,
    handoff_artifacts: dict[str, Path] | None = None,
    fingerprint: str | None = None,
)
```

| Param | Notes |
|---|---|
| `config` | Path, stem, or already-loaded dict |
| `name` | Overrides `[run].name` when set |
| `log_to_console` / `tty_bar` | Used when `sink` is omitted (builds `LocalFsSink`) |
| `ledger` | Orchestration; default `LocalFsLedger` |
| `sink` | Telemetry; default `LocalFsSink` |
| `preflight_hook` | Optional; return `False` or raise `PreflightCancel` to cancel |
| `parent` | Parent matrix/campaign linkage written into metadata |
| `params_overlay` | Merged onto `[params]` (matrix cell / handoff) |
| `handoff_artifacts` | Stem → Path map materialized for this run |
| `fingerprint` | Precomputed fingerprint when known (e.g. from `RunSpec`) |

### Properties

| Property | Type | Notes |
|---|---|---|
| `id` | `str` | Stamp id `YYYYMMDD_HHMMSS_<stem>` |
| `dir` | `Path` | Run result directory |
| `status` | `str` | `running` \| `complete` \| `failed` \| `cancelled` |
| `params` | `dict` | Resolved params after overlays / handoff |
| `handoff_artifacts` | `dict[str, Path]` | Stem → path under `run_dir/handoff/` (and pins) |
| `fingerprint` | `str` | `sha256:…` of canonical fingerprint payload |

### Methods

| Method | Notes |
|---|---|
| `preflight()` | Structural `check_config` + optional `preflight_hook`; cancel → `PreflightCancel` / status `cancelled` |
| `check_config()` | Structural defaults; overridable |
| `add_metric(key, value)` | Write scalar into `metrics.run` |
| `add_item_metric(item_id, key, value)` | Write into `metrics.items[item_id]` |
| `add_item_metrics(item_id, mapping)` | Bulk item metrics |
| `get_metrics()` | Current metrics dict |
| `write_to_log(msg)` | Append to run log |
| `output_path(*parts)` | Path under `run_dir/output/` |
| `write_output(name, data)` | Write bytes/text under `output/` |
| `pin_artifact(stem, path)` | Record pin in `metadata.pins` (path relative to run dir) |
| `complete()` | Mark complete; flush artifacts |
| `fail(exc=None)` | Mark failed |
| `__enter__` / `__exit__` | Context manager; `__exit__` finalizes if still `running` |

### `PreflightCancel`

Exception raised (or signaled via hook returning `False`) to cancel a run before the runner body. Does not count as a runtime failure.

## `MatrixRun`

### Constructor

```python
MatrixRun(
    config: str | Path | dict,
    *,
    name: str | None = None,
    cell_ids: list[str] | None = None,
    ledger: Ledger | None = None,
    sink: Sink | None = None,
    repeats: int | None = None,
    max_failures: int | None = None,
)
```

| Param | Notes |
|---|---|
| `cell_ids` | Optional filter; only these cells run |
| `repeats` / `max_failures` | Override config when set (campaign drive uses these) |

### Methods

| Method | Notes |
|---|---|
| `execute(runner)` | Reuse → preflight → shortfall Runs → stats/compare → figures. Locally calls `runner`; on coordinator enqueues `RunSpec`s |
| `resume(cls, dir)` | Classmethod: reopen matrix result dir and continue shortfall |
| `compare()` | Rebuild `compare.json` and `figures/` from existing `stats.json` |

## `CampaignRun`

### Constructor

```python
CampaignRun(
    config: str | Path | dict,
    *,
    name: str | None = None,
    phase_ids: list[int | str] | None = None,
    ledger: Ledger | None = None,
    sink: Sink | None = None,
)
```

| Param | Notes |
|---|---|
| `phase_ids` | Optional filter; only these phases run (others `skipped`) |

### Methods

| Method | Notes |
|---|---|
| `execute(runner)` | Phase loop: apply handoff → drive child matrix → `select_winner` → merge handoff |
| `resume(cls, dir)` | Classmethod: reopen campaign dir; restore `handoff.json`; skip ok phases |
| `select_winner(...)` | Internal: pick winner cell from stats (or `winner_cell` / `force_cell`) |

## `main`

```python
main(runner: Callable[[Run], None]) -> int
```

Parses argv and runs local drive, coordinator serve(+drive), or worker claim loop. See [CLI](cli.md).

| Exit code | Meaning |
|---|---|
| `0` | Success |
| `1` | Usage / config error |
| `2` | Run / matrix / campaign failed |
| `3` | Cancelled (preflight) |
| `4` | Network / ledger error |

## Path helpers

| Symbol | Behavior |
|---|---|
| `resolve_config_path(name)` | Bare stem → `bench_run/configs/run/<stem>.toml`; absolute/relative paths unchanged if they exist |
| `resolve_matrix_config_path(name)` | Same under `bench_run/configs/matrix/` |
| `resolve_campaign_config_path(name)` | Same under `bench_run/configs/campaign/` |

Related: [Concepts](concepts.md), [Lifecycle](lifecycle.md), [Artifacts](artifacts.md), [Package](package.md).
