# MPSC2 0.3.3a1 — Linux multiplayer

This alpha adds **headless Linux x86_64 support for SC2 4.10.0 / Base75689**.
Run 2–8 independent SC2 processes and API clients with the same `run_game`,
`run_game_async`, BotAI and `team_ids` APIs used on macOS and Windows.

- Support stepped and realtime matches, FFA, 3v1, 2v2 and larger team layouts.
- Run normal-resource mining, construction, unit production and research.
- Analyze replays headlessly, including selected players with native IDs ≥4.
- Check Linux installation, compiler and executable identity with `mpsc2 doctor`.
- Preserve existing macOS and Windows native helper sources and profiles.

## Install and run

Requires **Python 3.10+**, x86_64 Linux, GCC and a separately installed SC2
4.10 Linux distribution. Install the attached wheel, or install the tagged source:

```sh
git clone --branch v0.3.3a1 https://github.com/devindeng94/mpsc2.git
cd mpsc2
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
export SC2PATH="/path/to/StarCraftII"
python -m mpsc2 doctor --sc2-version 4.10
python examples/multiplayer.py --players 4 --teams 0 0 1 1 --realtime --output reports/linux-2v2
```

Use a fresh output directory for each match. See the
[Linux guide](https://github.com/devindeng94/mpsc2/blob/v0.3.3a1/docs/linux.md)
for economy games, replay analysis and the lowercase `maps/` requirement.
The wheel includes the helper source and maps; examples are in the source archive.
This release is available on GitHub and is not a PyPI publication.

## Validation

- Linux source and installed wheel: **361 passed, 3 skipped** each.
- Live Linux stepped and realtime games with every player count from **2 to 8**.
- Four-player FFA, 3v1 and 2v2; four/eight-player realtime economy;
  mixed-race production/research; replay views 0, 4 and 8; failure cleanup.
- macOS: **359 passed, 5 skipped**, plus a live four-player realtime regression.
- Windows native helpers are unchanged. This Linux release has no new live
  Windows run; earlier Windows measurements remain documented.

The [validation record](https://github.com/devindeng94/mpsc2/blob/v0.3.3a1/evidence/2026-11-01/linux-validation.json)
retains the scope and limitations. One eight-player expansion fixture missed a
Zerg expansion; the separate eight-player production/research fixture passed.

## Alpha boundaries

Linux support requires the exact verified executable SHA256
`115f65a49191c504f6336f7d5b7818b23dbba3d7a45cacf9142c86c959abaa41`.
The helper changes only session-owned process memory; installed SC2 files remain
unchanged. Other hashes fail validation. Multiplayer clients run on one host and
use the bundled research scenarios. RGB rendering, distributed hosts, arbitrary
multiplayer maps and more than eight players are not supported.

The release assets include a wheel, source distribution and `SHA256SUMS.txt`.
SC2 binaries and game data are not included.
