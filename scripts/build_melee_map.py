"""Build the four-base economy fixture from Blizzard's pinned empty terrain."""
from __future__ import annotations

import hashlib
from pathlib import Path

from build_map import build
from mpsc2.arena import runtime_script


def build_melee(output: Path | None = None) -> Path:
    return build(
        output or Path(__file__).resolve().parents[1] / "maps/MPSC2Melee.SC2Map",
        script=runtime_script([0, 0, 1, 1], 900, scenario="melee").encode(),
        title="MPSC2 Four-Player Economy",
    )


if __name__ == "__main__":
    path = build_melee()
    print(f"Built {path}\nSHA256: {hashlib.sha256(path.read_bytes()).hexdigest()}")
