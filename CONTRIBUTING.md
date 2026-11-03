# Contributing

Use Python 3.10 or newer. The supported compatibility target is pinned to
burnysc2 7.3.0. Do not loosen that pin without checking imports, callbacks,
observation preparation and live game/replay behavior.

```sh
python -m pip install -r requirements-dev.txt
python scripts/check_docs.py
python -m pytest -q
```

Offline tests require no game installation. CI is configured for Python 3.10/3.13
on Linux/macOS/Windows and 3.11/3.12 on Linux, and builds a wheel/sdist.
Native engine checks require a supported executable and `clang` on macOS,
MinGW-w64 GCC on Windows or GCC on Linux; they are opt-in and are not simulated by CI.

Start with the [installation guide](docs/installation.md) for environment setup.
The root requirements files use `pyproject.toml` as their dependency source of
truth; the historical environment snapshot is not the current development lock.

## Design boundaries

- Preserve upstream object identity. Add shims for public modules instead of
  copying BotAI/unit/economy implementations.
- Keep standard-game delegation separate from the native multiplayer lifecycle.
  Reject unsupported options before opening processes.
- Input order is not native join order. Use the actual ID mapping for teams,
  observations and results. Never infer guest IDs from process indices.
- Preserve independent processes, sockets, ownership, native results and fog.
  Do not substitute computer opponents or one shared-control client.
- Scope native cleanup to owned processes. Never use a system-wide process kill
  or patch an installed SC2 binary.
- The macOS and Windows lobby bridges change host data only. The macOS observation guard changes
  a seven-byte branch on a process-private executable page; Windows uses a
  narrowly checked exception handler without changing code bytes. Linux changes
  three host count immediates and a five-byte observation branch on verified
  process-private pages, preserving native initialization and readiness. Keep each
  profile's whole-file hash, runtime instruction and memory-state checks;
  refuse startup if any check fails. Never modify simulation or research rules.
- Keep maps, bridge source, templates and license notices in built distributions.
  Do not include replays, videos, engine logs, game executables or game data.

## Map maintenance

The source terrain and its MIT notice are under `maps/vendor`. Trigger rules
are in `maps/source` and `src/mpsc2/*.galaxy`. Rebuild deterministically:

```sh
python scripts/build_map.py
python scripts/build_melee_map.py
cp maps/MPSC2TeamArena.SC2Map src/mpsc2/assets/
cp maps/MPSC2Melee.SC2Map src/mpsc2/assets/
python -m pytest -q
```

If a deliberate map change alters its checksum, review the resulting MPQ
contents and update the corresponding guard in `arena.py`. The tests check
reproduction and equality between repository and installed map copies.
Do not silently accept arbitrary checksums.

## Engine checks

Run `python -m mpsc2 doctor` first. These commands launch local SC2 processes
(headless on Linux). Use fresh output paths:

On Linux, see the [Linux guide](docs/linux.md) for the exact Base75689 executable,
compiler and map-directory requirements. Cover every count in stepped and
realtime mode, macro/research, selected-player replays and owned-process cleanup.

On Windows, add `--sc2-version Base75689`, `Base93333` or `Base98370` to the
player-count and alpha validation scripts to exercise each profile. Replay
playback selects its engine from the recorded base build. See the
[three-build guide](docs/windows-three-build-validation.md) for measured
coverage and the difference between startup hashes and actual ability tables.

```sh
python scripts/validate_api.py --output reports/api-new
python scripts/validate_player_counts.py --output reports/counts-new
python scripts/validate_player_counts.py --realtime --output reports/counts-realtime-new
python scripts/validate_player_counts.py --scenario melee --output reports/counts-melee-new
python scripts/validate_alpha.py --phase races --skip-research --output reports/races-new
python scripts/validate_alpha.py --phase races --output reports/research-new
python scripts/verify_research_replay.py reports/research-new --playback
python scripts/validate_alpha.py --phase arena --output reports/ffa-new
python scripts/validate_alpha.py --phase failures --output reports/failure-new
python examples/versus_computer.py path/to/standard.SC2Map --output reports/computer-new
python examples/full_game.py --teams 7 9 7 9 --output reports/economy-new
python scripts/verify_economy_replay.py reports/economy-new
python examples/full_game.py --realtime --teams 7 9 7 9 --output reports/realtime-new
python scripts/verify_economy_replay.py reports/realtime-new
python scripts/validate_api.py --output reports/api-with-replay-new --replay reports/realtime-new/game.SC2Replay
```

The API integration script checks two sequential four-player matches with distinct sessions,
team metadata, owned/allied units, callbacks, stepped/realtime execution and
complete replay results. Its optional economy replay checks observer handling
of structures. The full-game example checks mining, spending, building,
production, expansion and combat; the separate replay verifier checks tracker
events and journals. Retain compact evidence of live tests without committing
large local report directories.

Player-count checks must cover every advertised count, not only the endpoints.
Retain failed attempts alongside successes in local reports, and identify retries
in compact evidence. `NativeFourSession` is a compatibility wrapper; new session
code belongs in `NativeMultiplayerSession`. The bridge's historical C filename is
retained for provenance, but its arrays and readiness thresholds use the requested
count. Where a profile uses a slot-15 readiness sentinel, it must remain outside
the playable roster. Linux preserves normal readiness instead of using a sentinel.
Research regressions must exercise native IDs >=4, own upgrade callbacks,
independent replay tracker completions and selected-player replay playback.

See [the alpha audit](docs/alpha-validation.md) for the upstream test comparison,
standard async/batch checks, observer checks and measured coverage. The upstream
runner requires an explicitly provided checkout matching the installed pinned
dependency; it never fetches and executes an unpinned branch automatically.

## Package checks and release preparation

```sh
python -m build --outdir dist/current
python -m twine check dist/current/*
python -m venv /tmp/mpsc2-package-check
/tmp/mpsc2-package-check/bin/python -m pip install dist/current/mpsc2-*.whl
cd /tmp
/tmp/mpsc2-package-check/bin/python -m mpsc2 maps
```

Check installed imports and bundled map resolution from outside the checkout.
For native changes, rerun the engine checks against the installed wheel too.
Update the version in `pyproject.toml` and `src/mpsc2/__init__.py`, the changelog,
support matrix, and validation evidence. Check that source archives contain
examples/tests/map sources and that wheels contain the maps, templates, C source,
typing marker and original third-party notices.

Publishing is a separate maintainer action. This project does not automatically
upload packages, push branches or create releases. The backend remains alpha
until broader platform/build and long-run validation supports a stronger claim.
See the [GitHub publishing guide](docs/publishing.md) and
[prepared alpha release notes](docs/release-notes-0.3.3a2.md).

Report issues with Python, burnysc2 and SC2 versions, operating system,
`mpsc2 doctor` output, reproduction steps and a relevant report excerpt.
Review paths/player names before sharing logs. Contributions use the project's
MIT license and preserve upstream attribution.
