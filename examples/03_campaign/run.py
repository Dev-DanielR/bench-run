"""Phased campaign example entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import bind_example_root

bind_example_root(Path(__file__).resolve().parent)

from bench_run import Run, main


def runner(run: Run) -> None:
    mode = run.params.get("mode_a", "y")
    # Prefer mode_a == "x" so cell_a wins phase 1 and hands off that knob.
    score = 0.9 if mode == "x" else 0.5
    run.add_metric("accuracy", score)
    run.write_output("model.bin", b"weights")
    run.pin_artifact("model", "output/model.bin")


if __name__ == "__main__":
    raise SystemExit(main(runner))
