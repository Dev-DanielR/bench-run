# Config schemas

Workspace root: `BENCH_RUN_ROOT` if set; else `cwd/.bench-run` when that directory exists; else process cwd. All relative paths in configs resolve from that root. Configs live under `configs/{run,matrix,campaign,execution}/`.

## Run — `configs/run/`

```toml
[run]
name = "baseline"                 # required unless Run(..., name=) is passed
# fingerprint_keys = []           # optional; subset of params keys included in fingerprint
# handoff_artifacts = []          # optional; output stems eligible for pin / campaign handoff

[data]
# root = "data/my_dataset"        # optional; if set, path must exist at preflight

[params]
# free-form experiment knobs
```

| Key | Default | Notes |
|---|---|---|
| `run.name` | — | Required in TOML unless constructor `name=` supplied |
| `run.fingerprint_keys` | `[]` | Params keys folded into fingerprint payload |
| `run.handoff_artifacts` | `[]` | Stems the runner may `pin_artifact`; campaign may promote them |
| `data.root` | unset | Dataset root under workspace |
| `params.*` | `{}` | Free-form; merged with matrix overlays and campaign handoff |

## Matrix — `configs/matrix/`

```toml
[matrix]
name = "factor_a"
repeats = 1                       # default 1
# max_failures = 1                # default = repeats when omitted
# figure_metrics = ["accuracy"]   # optional plot order
# baseline_cell = "on"            # optional; else first cell id in config order

[[matrix.cells]]
id = "on"
config = "baseline.toml"
# params = { seed = 1 }           # optional overlay dict merged onto run params

[[matrix.cells]]
id = "off"
config = "ablation_off.toml"
```

| Key | Default | Notes |
|---|---|---|
| `matrix.name` | — | Required |
| `matrix.repeats` | `1` | Target completed runs per cell |
| `matrix.max_failures` | `repeats` | Failed runs allowed per cell before cell `failed` |
| `matrix.figure_metrics` | `[]` | Preferred figure metric order; empty → built-in preference list |
| `matrix.baseline_cell` | first cell id | Used by `compare.json` |
| `matrix.cells[].id` | — | Required unique cell id |
| `matrix.cells[].config` | — | Run config path or stem |
| `matrix.cells[].params` | `{}` | Overlay merged onto the child run's `[params]` |

Campaign-driven matrices: use the child matrix's `max_failures`, unless `[campaign].max_failures` is set (then that override applies).

## Campaign — `configs/campaign/`

```toml
[campaign]
name = "phased"
repeats = 5                       # applied to child matrices when driving a phase
# max_failures = 5                # optional override of child matrix max_failures
continue_on_fail = false

[[campaign.phases]]
id = 1                            # int or string
name = "stage_a"
matrix = "factor_a.toml"
winner_metric = "accuracy"
winner_direction = "max"          # default "max"
handoff_keys = ["mode_a"]
# winner_cell = "on"              # optional force-select; alias: force_cell
# force_cell = "on"               # same as winner_cell; both supported, identical meaning
```

| Key | Default | Notes |
|---|---|---|
| `campaign.name` | — | Required |
| `campaign.repeats` | — | When driving a phase, overrides the child matrix's `repeats` |
| `campaign.max_failures` | unset | When set, overrides the child matrix's `max_failures` |
| `campaign.continue_on_fail` | `false` | If true, continue later phases after a failed phase; preflight cancel still halts |
| `phases[].id` | — | Int or string phase id |
| `phases[].name` | — | Display name |
| `phases[].matrix` | — | Matrix config path or stem |
| `phases[].winner_metric` | — | Metric key from stats / run scalars |
| `phases[].winner_direction` | `"max"` | `"max"` or `"min"` |
| `phases[].handoff_keys` | `[]` | Param keys copied from winner into cumulative handoff |
| `phases[].winner_cell` / `force_cell` | unset | Force the winner cell; both keys are aliases of each other |

## Execution — `configs/execution/`

```toml
[coordinator]
name = "lab_cluster"
bind = "0.0.0.0:8443"             # host:port; host parsed from bind
# data_dir = "results/_coordinator"   # default
# auth = { token_env = "BENCH_RUN_TOKEN" }
# uvicorn_workers = 1             # always 1: driver is in-process
# lease_scan_s = 10               # reclaim expired leases

[worker]
url = "https://coordinator.example:8443"
# auth = { token_env = "BENCH_RUN_TOKEN" }

[worker.claim]
poll_s = 2.0
lease_s = 300
heartbeat_fraction = 3            # heartbeat every lease_s / 3
# matrix_ids = []                 # optional claim filters
# campaign_ids = []
# config_stems = []
```

| Key | Default | Notes |
|---|---|---|
| `coordinator.bind` | — | `host:port` listen address |
| `coordinator.data_dir` | `results/_coordinator` | Server-side ledger store root |
| `coordinator.auth.token_env` | unset | Env var holding shared bearer token |
| `coordinator.uvicorn_workers` | `1` | Single process; MatrixRun/CampaignRun driver lives in-process |
| `coordinator.lease_scan_s` | `10` | How often the server re-queues expired claims |
| `worker.url` | — | Coordinator base URL |
| `worker.auth.token_env` | unset | Same token scheme as coordinator |
| `worker.claim.poll_s` | `2.0` | Idle poll interval seconds |
| `worker.claim.lease_s` | `300` | Claim lease duration seconds |
| `worker.claim.heartbeat_fraction` | `3` | Heartbeat period = `lease_s / heartbeat_fraction` |
| `worker.claim.matrix_ids` | unset | Optional filter: only claim these matrix ids |
| `worker.claim.campaign_ids` | unset | Optional filter: only claim these campaign ids |
| `worker.claim.config_stems` | unset | Optional filter: only claim these run config stems |

See [Distributed execution](execution.md).
