"""Leave a matrix with shortfall so --resume has work to do.

Runs factor_a once with repeats=1, then bumps the on-disk repeats target to 2
and marks the matrix running again.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import bind_example_root

EXAMPLE_ROOT = bind_example_root(Path(__file__).resolve().parent)

from bench_run import MatrixRun, Run
from bench_run.artifacts import read_manifest, read_metadata, write_manifest, write_metadata
from bench_run.config import dump_toml, load_toml


def runner(run: Run) -> None:
    mode = run.params.get("mode", "off")
    run.add_metric("accuracy", 0.9 if mode == "on" else 0.5)


def main() -> int:
    with MatrixRun("factor_a.toml", repeats=1) as matrix:
        matrix.execute(runner)
        result_dir = matrix.dir

    cfg_path = result_dir / "config.toml"
    cfg = load_toml(cfg_path)
    cfg.setdefault("matrix", {})["repeats"] = 2
    dump_toml(cfg, cfg_path)

    manifest = read_manifest(result_dir)
    manifest["repeats"] = 2
    for cell in manifest["cells"]:
        if cell.get("status") == "ok" and len(cell.get("completed_run_ids") or []) < 2:
            cell["status"] = "running"
    write_manifest(result_dir, manifest)

    meta = read_metadata(result_dir)
    meta["status"] = "running"
    meta["finished_at"] = None
    write_metadata(result_dir, meta)

    rel = result_dir.relative_to(EXAMPLE_ROOT)
    print(f"partial matrix ready: {rel.as_posix()}")
    print(f"resume with: python run.py --resume {rel.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
