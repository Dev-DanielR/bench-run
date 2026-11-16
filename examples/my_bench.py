"""Minimal project entrypoint for bench-run."""

from __future__ import annotations

from bench_run import Run, main


def runner(run: Run) -> None:
    run.addMetric("accuracy", 0.8)
    path = run.outputPath("note.txt")
    path.write_text("ok\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main(runner))
