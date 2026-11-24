"""Local filesystem sink: log.txt, metrics.json, TTY progress bars."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from bench_run.artifacts import utc_now_iso, write_metrics
from bench_run.sink.base import (
    Event,
    LogLine,
    MetricSet,
    ProgressLine,
    Scope,
)


def _resolve_tty_bar(tty_bar: bool | None) -> bool:
    if tty_bar is None:
        return bool(sys.stderr.isatty())
    return bool(tty_bar)


class LocalFsSink:
    def __init__(
        self,
        *,
        log_to_console: bool = True,
        tty_bar: bool | None = None,
    ) -> None:
        self._log_to_console = log_to_console
        self._tty_bar = _resolve_tty_bar(tty_bar)
        self._bar_depth = 0

    def with_options(
        self,
        *,
        log_to_console: bool | None = None,
        tty_bar: bool | None = None,
    ) -> LocalFsSink:
        return LocalFsSink(
            log_to_console=self._log_to_console
            if log_to_console is None
            else bool(log_to_console),
            tty_bar=self._tty_bar if tty_bar is None else bool(tty_bar),
        )

    @property
    def _bar_active(self) -> bool:
        return self._bar_depth > 0

    def emit(self, scope: Scope, event: Event) -> None:
        if isinstance(event, (LogLine, ProgressLine)):
            self.append_log_line(scope, event.msg)
        elif isinstance(event, MetricSet):
            self.write_metric_set(scope, event.metrics)

    def append_log_line(self, scope: Scope, msg: str) -> str:
        """Append ISO line to scope log.txt (+ optional console). Returns the line."""
        line = f"{utc_now_iso()} {msg}"
        if scope.dir is not None:
            path = Path(scope.dir) / "log.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fp:
                fp.write(line + "\n")
        if self._log_to_console and not self._bar_active:
            print(line, flush=True)
        return line

    def write_metric_set(self, scope: Scope, metrics: dict[str, Any]) -> None:
        if scope.dir is None:
            return
        write_metrics(Path(scope.dir), metrics)

    @contextmanager
    def progress_bar(
        self,
        scope: Scope,
        total: int | None = None,
        *,
        title: str | None = None,
        tty_bar: bool | None = None,
    ) -> Iterator[Any]:
        use_tty = self._tty_bar if tty_bar is None else bool(tty_bar)
        use_bar = bool(use_tty) and sys.stderr.isatty()
        if use_bar:
            from alive_progress import alive_bar

            kwargs: dict[str, Any] = {"file": sys.stderr}
            if title:
                kwargs["title"] = title
            self._bar_depth += 1
            try:
                with alive_bar(total, **kwargs) as bar:
                    yield bar
            finally:
                self._bar_depth -= 1
            return

        class _NoopBar:
            text = ""

            def __call__(self, *args: Any, **kwargs: Any) -> None:
                return None

        yield _NoopBar()

    def metrics_snapshot(self, scope: Scope) -> dict[str, Any] | None:
        return None

    def log_text(self, scope: Scope) -> str | None:
        if scope.dir is None:
            return None
        path = Path(scope.dir) / "log.txt"
        if path.is_file():
            return path.read_text(encoding="utf-8")
        return None


