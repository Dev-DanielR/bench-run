"""Shared bootstrap for example entrypoints.

Sets ``BENCH_RUN_ROOT`` to the example directory (flat workspace: ``configs/``,
``results/``) and puts ``examples/`` on ``sys.path`` so ``import project`` works.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def bind_example_root(example_root: Path | str) -> Path:
    root = Path(example_root).resolve()
    os.environ["BENCH_RUN_ROOT"] = str(root)

    examples = root.parent  # examples/<name> -> examples/
    examples_s = str(examples)
    if examples_s not in sys.path:
        sys.path.insert(0, examples_s)
    return root
