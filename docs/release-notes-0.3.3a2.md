# MPSC2 0.3.3a2 — separate macOS compatibility engine

This document records the earlier development build and its validation. These
changes ship in [0.3.4a1](release-notes-0.3.4a1.md), which also includes the
multiplayer service and Linux startup recovery.

This alpha restores research functionality after the tested macOS
**5.0.17 / Base98310** retail update by preparing a separately selected
**5.0.15 / Base96883** installation. The actual Base98310 executable remains
unsupported: it did not expose a usable SC2 API during local validation.

## Setup

Install the 0.3.3a2 wheel or this source checkout with Python 3.10+, then run:

```sh
python -m mpsc2 prepare-macos-compat \
  --installation "/Applications/StarCraft II" \
  --destination "$PWD/.mpsc2/StarCraftII-96883"
export SC2PATH="$PWD/.mpsc2/StarCraftII-96883"
python -m mpsc2 doctor --sc2-version Base96883
python -m mpsc2.probe --output reports/compat-probe.json
python examples/minimal_four_player.py
```

Examples are included in the source archive. Use a new destination and report
path. A Mac C compiler is still needed for three or more independent clients.

Setup downloads approximately 95 MB directly from Blizzard, verifies all app
files, and retains the original signatures. The compatibility root owns its
build configuration and shares the installed content cache. Retail executables
and build selection stay unchanged. Existing BotAI, team, realtime and replay
interfaces continue to work with the explicitly selected root.

The setup command itself does not run gameplay tests. The
[validation record](../evidence/2026-11-01/macos-compat-engine.json) records the
live tests performed for this change, including failed attempts and retries.
Existing Windows/Linux profiles and all native helper sources are unchanged;
this release has no new live Windows or Linux run.

## Validation

- Initial source and installed wheel: **403 passed, 5 skipped** each on this Mac.
- After the November 2 diagnostic additions: source **417 passed, 5 skipped**.
  This retest adds exact-build checking and an optional Ping-only connection
  probe; it does not add Base98310 support. See the
  [retest record](../evidence/2026-11-02/macos-98310-retest.json).
- Stepped gameplay with every count from **2 through 8** independent clients.
- **4- and 8-player realtime** mining, worker training and construction, with no
  manual step requests.
- **8-player mixed-race** economy, production and research using normal resources;
  upgrade callbacks and native replay tracker events for every player.
- Replay views **0 and 8**, including visible weapon upgrades and selected-player
  upgrade observations.
- One BotAI versus Computer, standard batch games and a standard two-client game.
- Original app signatures, retail executable/build selection, and native helper
  source hashes preserved. No task-owned SC2 engine remains after validation.

The standard lifecycle still emits an upstream HTTP-session cleanup warning,
also present in earlier validation runs. Gameplay and port-release assertions
pass; this compatibility change does not fix that existing warning.

## Boundaries

This route uses **5.0.15 rules and data**, not 5.0.17 balance changes. It was
validated on a Mac updated from 5.0.15; a fresh installation without historical
content is not yet validated. Later retail cache cleanup may remove required
content. One eight-client join timed out during validation and its isolated
retry passed; the existing intermittent startup limitation remains documented.

The package includes no Blizzard executables or game data. This change does
not add distributed-host play, arbitrary native engine versions or more than
eight clients. See [installation](installation.md),
[the investigation](macos-98310-investigation.md) and
[known issues](known-issues.md) for details.
