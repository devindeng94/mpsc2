# MPSC2 0.3.1a2 — public alpha

MPSC2 adds team-based multiplayer self-play to familiar python-sc2 APIs. It runs
2–8 independent StarCraft II clients, supports arbitrary team labels, stepped
and realtime play, bundled combat/economy scenarios, and replay/batch APIs.
The compatibility target is burnysc2 7.3.0; Python 3.10+ is required.

The multiplayer backend currently requires macOS and the exact supported
SC2 5.0.15 / Base96883 executable. It uses guarded runtime helpers; installed
game files remain unchanged. The game is installed separately.

This version fixes MPSC2-001: the engine's private opponent-upgrade observation
lookup underflows for native player IDs ≥4. Own upgrades, callbacks and simulation
are preserved, including affected selected-player replay views.

Validation includes normal-resource research for every player count from 2–8,
four-player realtime without manual stepping, four/eight-player replay checks,
and 227 offline tests on Python 3.10 and 3.13 from source and installed wheels.

Known limits include intermittent startup timeouts, three missed expansions in
the bounded eight-player macro fixture, no Windows/Linux multiplayer backend,
and no arbitrary-map, remote-host or long-training validation. This is an alpha
for reproducible local research, not a guarantee for every SC2 workload.

Install from the repository with `python -m pip install .`, or install the attached
wheel. Run `python -m mpsc2 doctor` and follow `docs/installation.md` before launching
a game. Documentation, requirements files, examples, GitHub templates and offline
CI are included. Original code is MIT licensed with upstream notices retained.
