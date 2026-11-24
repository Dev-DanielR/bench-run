from bench_run.sink.base import (
    Event,
    LogLine,
    MetricSet,
    ProgressLine,
    Scope,
    Sink,
)
from bench_run.sink.local import LocalFsSink

__all__ = [
    "Event",
    "LogLine",
    "MetricSet",
    "ProgressLine",
    "Scope",
    "Sink",
    "LocalFsSink",
]

try:
    from bench_run.sink.coordinator import CoordinatorSink

    __all__.append("CoordinatorSink")
except ImportError:
    pass
