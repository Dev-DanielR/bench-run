"""Shared bootstrap for example entrypoints.

Each example keeps configs under ``./bench_run/``, which would shadow the
installed ``bench_run`` package when the example dir is on ``sys.path[0]``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def bind_example_root(example_root: Path | str) -> Path:
    root = Path(example_root).resolve()
    os.environ.setdefault("BENCH_RUN_ROOT", str(root))

    def _is_example_dir(entry: str) -> bool:
        if entry in ("", "."):
            return True
        try:
            return Path(entry).resolve() == root
        except OSError:
            return False

    sys.path[:] = [p for p in sys.path if not _is_example_dir(p)]

    examples = root.parent  # examples/<name> -> examples/
    examples_s = str(examples)
    if examples_s not in sys.path:
        sys.path.insert(0, examples_s)

    repo = root.parents[1]  # examples/<name> -> repo root
    repo_s = str(repo)
    if repo_s not in sys.path:
        sys.path.insert(0, repo_s)
    return root
