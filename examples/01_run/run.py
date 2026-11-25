"""Single-run example — wraps project.baseline."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import bind_example_root

bind_example_root(Path(__file__).resolve().parent)

from bench_run import Run, main
from project import baseline


def runner(run: Run) -> None:
    seed = int(run.params.get("seed", 0))
    accuracy, note = baseline.run(seed=seed)
    run.add_metric("accuracy", accuracy)
    run.output_path("note.txt").write_text(note, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main(runner))
