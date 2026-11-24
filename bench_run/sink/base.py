"""Sink protocol: telemetry events (log, progress, metrics)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Literal, Protocol, Union

LayerName = Literal["run", "matrix", "campaign"]


@dataclass(frozen=True)
class Scope:
    layer: LayerName
    id: str
    dir: Path | None = None


@dataclass(frozen=True)
class LogLine:
    msg: str


@dataclass(frozen=True)
class ProgressLine:
    msg: str


@dataclass(frozen=True)
class MetricSet:
    """Full metrics snapshot ``{run: {...}, items: {...}}``."""

    metrics: dict[str, Any]


Event = Union[LogLine, ProgressLine, MetricSet]


class Sink(Protocol):
    def emit(self, scope: Scope, event: Event) -> None: ...

    def progress_bar(
        self,
        scope: Scope,
        total: int | None = None,
        *,
        title: str | None = None,
        tty_bar: bool | None = None,
    ) -> Iterator[Any]: ...

    def with_options(
        self,
        *,
        log_to_console: bool | None = None,
        tty_bar: bool | None = None,
    ) -> Sink: ...

    def metrics_snapshot(self, scope: Scope) -> dict[str, Any] | None: ...

    def log_text(self, scope: Scope) -> str | None: ...
