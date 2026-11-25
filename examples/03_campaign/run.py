"""Phased campaign example — dispatch (phase_id, cell_id) → project cell."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import bind_example_root

bind_example_root(Path(__file__).resolve().parent)

from bench_run import Run, main
from project import cell1a, cell1b, cell2a, cell2b

CELLS = {
    (1, "a"): cell1a,
    (1, "b"): cell1b,
    (2, "a"): cell2a,
    (2, "b"): cell2b,
}


def runner(run: Run) -> None:
    phase = int(run.params.get("phase") or (run.parent or {}).get("phase_id") or 1)
    cell_id = (run.parent or {}).get("cell_id") or "a"
    mod = CELLS[(phase, cell_id)]
    mode = run.params.get("mode", "y")

    if phase == 1:
        score, weights = mod.run(mode=mode)
    else:
        path = run.handoff_artifacts.get("model")
        if path is None:
            raise RuntimeError("phase 2 expected handoff artifact stem 'model' from phase 1")
        prior = Path(path).read_bytes()
        score, weights = mod.run(mode=mode, prior=prior)

    run.add_metric("accuracy", score)
    run.write_output("model.bin", weights)
    run.pin_artifact("model", "output/model.bin")


if __name__ == "__main__":
    raise SystemExit(main(runner))
