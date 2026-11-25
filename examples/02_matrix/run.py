"""Matrix ablation example — cell_id → project.on / project.off."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import bind_example_root

bind_example_root(Path(__file__).resolve().parent)

from bench_run import Run, main
from project import off, on

CELLS = {
    "on": on,
    "off": off,
}


def runner(run: Run) -> None:
    cell_id = (run.parent or {}).get("cell_id") or run.params.get("mode", "off")
    mod = CELLS[cell_id]
    mode = run.params.get("mode", cell_id)
    score, mode_out = mod.run(mode=mode)
    run.add_metric("accuracy", score)
    run.output_path("mode.txt").write_text(f"{mode_out}\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main(runner))
