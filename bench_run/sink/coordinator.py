"""Worker sink: local working-copy writes + package buffer for telemetry."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from bench_run.sink.base import Event, LogLine, MetricSet, ProgressLine, Scope
from bench_run.sink.local import LocalFsSink


class CoordinatorSink:
    """Delegates durable writes to LocalFsSink; buffers log/metrics per run id."""

    def __init__(
        self,
        *,
        log_to_console: bool = False,
        tty_bar: bool | None = False,
        local: LocalFsSink | None = None,
    ) -> None:
        self._local = local or LocalFsSink(
            log_to_console=log_to_console,
            tty_bar=tty_bar,
        )
        self._log_buf: dict[str, list[str]] = {}
        self._metrics_buf: dict[str, dict[str, Any]] = {}

    def with_options(
        self,
        *,
        log_to_console: bool | None = None,
        tty_bar: bool | None = None,
    ) -> CoordinatorSink:
        child = CoordinatorSink(local=self._local.with_options(
            log_to_console=log_to_console,
            tty_bar=tty_bar,
        ))
        child._log_buf = self._log_buf
        child._metrics_buf = self._metrics_buf
        return child

    def emit(self, scope: Scope, event: Event) -> None:
        if isinstance(event, (LogLine, ProgressLine)):
            line = self._local.append_log_line(scope, event.msg)
            if scope.layer == "run":
                self._log_buf.setdefault(scope.id, []).append(line + "\n")
        elif isinstance(event, MetricSet):
            self._local.write_metric_set(scope, event.metrics)
            if scope.layer == "run":
                self._metrics_buf[scope.id] = dict(event.metrics)

    @contextmanager
    def progress_bar(
        self,
        scope: Scope,
        total: int | None = None,
        *,
        title: str | None = None,
        tty_bar: bool | None = None,
    ) -> Iterator[Any]:
        with self._local.progress_bar(
            scope, total, title=title, tty_bar=tty_bar
        ) as bar:
            yield bar

    def metrics_snapshot(self, scope: Scope) -> dict[str, Any] | None:
        return self._metrics_buf.get(scope.id)

    def log_text(self, scope: Scope) -> str | None:
        parts = self._log_buf.get(scope.id)
        if parts:
            return "".join(parts)
        return self._local.log_text(scope)

    def clear_run(self, run_id: str) -> None:
        self._log_buf.pop(run_id, None)
        self._metrics_buf.pop(run_id, None)
