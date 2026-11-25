"""Halt a campaign on phase-1 boom, then clear fail so --resume can continue.

1. Ensures phase1 boom cell has fail=true
2. Runs phased.toml until continue_on_fail=false stops the campaign
3. Sets fail=false on the boom cell so the next phase-1 attempt can succeed
4. Prints the --resume command (phase 2 still pending; no handoff yet)
"""

from __future__ import annotations

import sys
from pathlib import Path

_EXAMPLE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_EXAMPLE_ROOT.parents[0]))

from _bootstrap import bind_example_root

EXAMPLE_ROOT = bind_example_root(_EXAMPLE_ROOT)

from bench_run import CampaignRun

sys.path.append(str(EXAMPLE_ROOT))
from run import runner

PHASE1 = EXAMPLE_ROOT / "configs" / "matrix" / "phase1.toml"


def _set_boom_fail(fail: bool) -> None:
    text = PHASE1.read_text(encoding="utf-8")
    needle_true = "params = { mode = \"z\", phase = 1, fail = true }"
    needle_false = "params = { mode = \"z\", phase = 1, fail = false }"
    target = needle_true if fail else needle_false
    if needle_true in text:
        text = text.replace(needle_true, target, 1)
    elif needle_false in text:
        text = text.replace(needle_false, target, 1)
    else:
        raise SystemExit("phase1.toml missing boom cell fail param line")
    PHASE1.write_text(text, encoding="utf-8")



def main() -> int:
    _set_boom_fail(True)
    campaign = CampaignRun("phased.toml")
    campaign.execute(runner)
    if campaign.status != "failed":
        print(
            f"error: expected campaign status failed, got {campaign.status!r}",
            file=sys.stderr,
        )
        return 1

    _set_boom_fail(False)
    result_dir = campaign.dir
    rel = result_dir.relative_to(EXAMPLE_ROOT)
    print(f"halted campaign ready: {rel.as_posix()}")
    print("  phase 1: failed (boom raised; no winner / handoff)")
    print("  phase 2: pending")
    print("  boom params.fail flipped to false for the next phase-1 attempt")
    print(f"resume with: python run.py --resume {rel.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
