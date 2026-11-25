"""Failure-modes example — wraps project.ok / project.boom."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import bind_example_root

bind_example_root(Path(__file__).resolve().parent)

from bench_run import Run, main
from project import boom, ok

CELLS = {
    "ok": ok,
    "boom": boom,
}


def runner(run: Run) -> None:
    cell_id = (run.parent or {}).get("cell_id") or "ok"
    mod = CELLS[cell_id]
    if cell_id == "boom":
        mod.run()
        return
    accuracy, text = mod.run()
    run.add_metric("accuracy", accuracy)
    run.output_path("ok.txt").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main(runner))
