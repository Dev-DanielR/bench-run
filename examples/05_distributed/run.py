"""Distributed coordinator/worker example entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import bind_example_root

bind_example_root(Path(__file__).resolve().parent)

from bench_run import Run, main


def runner(run: Run) -> None:
    mode = run.params.get("mode", "off")
    run.add_metric("accuracy", 0.9 if mode == "on" else 0.5)
    run.output_path("mode.txt").write_text(f"{mode}\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main(runner))
