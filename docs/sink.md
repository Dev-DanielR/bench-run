# Sink (telemetry)

**Sink** owns telemetry: logs, progress, and metrics. **Ledger** owns orchestration: outputs, manifests, stats/compare/figures, winners/handoff, claims, and terminal packages.

Layers (`Run` / `MatrixRun` / `CampaignRun`) emit typed events; they do not open `log.txt` or choose local vs distributed writers.

## Events

| Event | Meaning |
|---|---|
| `LogLine(msg)` | Append ISO line to scope `log.txt` (+ optional console) |
| `ProgressLine(msg)` | Same durable sink as log; used for orchestration status |
| `MetricSet(metrics)` | Full `{run, items}` snapshot → `metrics.json` (+ worker package buffer) |

`Scope` is `{layer: run|matrix|campaign, id, dir}`.

## Protocol

```python
class Sink(Protocol):
    def emit(self, scope: Scope, event: Event) -> None: ...
    def progress_bar(self, scope, total=None, *, title=None, tty_bar=None): ...
    def with_options(self, *, log_to_console=None, tty_bar=None) -> Sink: ...
    def metrics_snapshot(self, scope) -> dict | None: ...
    def log_text(self, scope) -> str | None: ...
```

## Backends

| Class | Role |
|---|---|
| `LocalFsSink` | Write under `scope.dir`; TTY bars via `alive-progress` |
| `CoordinatorSink` | Local working copy + buffer for multipart package (worker) |

`main` builds a sink from CLI flags and injects it alongside the ledger. If `sink` is omitted, layers default to `LocalFsSink`.

Worker package assembly reads log/metrics from `CoordinatorSink` (fallback: disk).

## Layer helpers

| Helper | Emits |
|---|---|
| `write_to_log` | `LogLine` |
| `progress_line` | `ProgressLine` |
| `progress_bar` | Sink bar context |
| `add_metric` / `add_item_metric(s)` | `MetricSet` |

`write_output` / `put_output` stay on **Ledger** (orchestration artifacts).
