"""Single-run example entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import bind_example_root

bind_example_root(Path(__file__).resolve().parent)

from bench_run import Run, main


def runner(run: Run) -> None:
    seed = int(run.params.get("seed", 0))
    run.add_metric("accuracy", 0.75 + seed * 0.01)
    path = run.output_path("note.txt")
    path.write_text(f"seed={seed}\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main(runner))
