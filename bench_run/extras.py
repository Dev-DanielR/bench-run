"""Optional-extra install hints (coord / figures)."""

from __future__ import annotations

_GIT = "git+https://github.com/Dev-DanielR/bench-run.git"

COORD_EXTRA_HINT = (
    "distributed roles require the coord extra: "
    f"pip install 'bench-run[coord]' "
    f"(from git: pip install 'bench-run[coord] @ {_GIT}')"
)

FIGURES_EXTRA_HINT = (
    "matrix figures require the figures extra: "
    f"pip install 'bench-run[figures]' "
    f"(from git: pip install 'bench-run[figures] @ {_GIT}')"
)
