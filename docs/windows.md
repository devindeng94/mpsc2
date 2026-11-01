# Windows multiplayer setup

Version **0.3.2a4** includes a separate Windows backend for 2–8 independent
python-sc2 clients, including the bundled team arena and economy scenarios.
The existing macOS Base96883 backend and observation guard remain intact.
Build selection now uses the [version/profile registries](version-profiles.md).
Use `python -m mpsc2 versions` to inspect them and `doctor --sc2-version 5.0.15`
to check Base98370. Use `5.0.14` for Base93333 or `4.10` for Base75689.
Base92440 has no native profile.

## Requirements

- 64-bit Windows and Python 3.10 or later.
- The exact validated **SC2 4.10 / Base75689**, **5.0.14 / Base93333** or
  **5.0.15 / Base98370** Windows executable and its
  complete game data, including `Support64`.
- **MinGW-w64 GCC targeting x86_64** for 3–8 clients. Two clients need no
  compiler or DLL. A portable w64devkit installation works.

Executable SHA256 values:

- Base75689: `b7cac088c463c64ce5ac84acafba546c8c2c13cb7df3613a9c09fb9b0e61f7f9`
- Base98370: `c68202849f8e64ed20d15bea0fb89f2c5b94028d075d9848e124a8264d130222`
- Base93333: `e67dcd28e5c5b21d3e4d9e38aada09ed522af28ac0cc5338d709357040493ee0`

Other Windows builds are refused by the multiplayer route. An installation's
newest build may differ: use `sc2_version="5.0.15"` to select Base98370.
The omitted-argument default remains Base93333, and standard games retain
upstream's build selection.

From the source directory, create an environment and install this checkout:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install .
$env:SC2PATH = "E:\StarCraft II"
$env:MPSC2_WINDOWS_CC = "D:\w64devkit\bin\gcc.exe"
.venv\Scripts\python.exe -m mpsc2 doctor --sc2-version 5.0.15
```

Use paths appropriate to your machine. `SC2PATH` is optional if Blizzard's
`Documents\StarCraft II\ExecuteInfo.txt` points to the installation.
`MPSC2_WINDOWS_CC` is optional when the appropriate `gcc.exe` is on PATH.
An invalid explicit compiler setting is reported rather than silently ignored.
No public PyPI release or upstream GitHub tag for this local change is assumed.

`doctor` checks the Windows executable hash, compiler availability, 64-bit
Python, `Support64`, and bundled maps. Readiness is a static prerequisite check;
only a live match confirms working game data, graphics, networking, and compiler.
The default diagnostic covers 3–8 clients and therefore checks the compiler;
two-client sessions themselves do not compile a helper.

## Run a match

```powershell
.venv\Scripts\python.exe examples/multiplayer.py --players 4 --teams 0 0 1 1 --sc2-version 5.0.15 --output reports/windows-first
```

Use a **fresh output directory** for every run. Omit `--teams` for free-for-all,
use `--teams 0 0 0 1` for 3v1, or choose any count from 2 through 8. Add
`--realtime` to use the engine clock. The Python API remains `run_game(...)`
with one distinct `BotAI` per player and the same `team_ids` arguments as macOS.

For economy and research validation:

```powershell
.venv\Scripts\python.exe scripts/validate_alpha.py --phase races --research-only --sc2-version 5.0.15 --output reports/windows-research
```

For the complete player-count matrix and realtime checks:

```powershell
.venv\Scripts\python.exe scripts/validate_player_counts.py --counts 2 3 4 5 6 7 8 --sc2-version 5.0.15 --output reports/windows-counts
.venv\Scripts\python.exe scripts/validate_player_counts.py --counts 4 --realtime --sc2-version 5.0.15 --output reports/windows-realtime
```

## What changed

The Windows engine also rejects CreateGame with more than two API participants.
Changing the OS name or executable path cannot remove this restriction.
`windows_session.py` validates the exact Windows binary, launches it with
`Support64` as its working directory, and loads a locally compiled helper into
the child processes owned by that session. Only the host enables lobby and
socket handling; every 3–8-player client enables the observation guard.
Standard games remain delegated to
burnysc2. No game executable or game data is patched on disk.

The helper verifies runtime instruction signatures and the rejected lobby's
state, participant count, roster, and absence of computer players. It promotes
that local lobby, forwards loopback discovery packets to every guest, and waits
for every player's native readiness. Each guest receives its own port pair.
MinHook 1.3.4 provides process-local socket interception; its source and BSD
license are packaged with MPSC2, so compilation needs no network downloads.

Windows counts **nonzero readiness pairs**, while the macOS build sums byte
values. The Windows hold therefore reserves two unused slots (14 and 15), set
atomically, until every real participant is ready. The macOS algorithm remains
unchanged. These slots do not become players. Teams, ownership, simulation,
actions, and native victory/defeat results still come from SC2.

Windows has the same private `3-player_id` upgrade-index bug at a different
instruction. Its read-only code mapping refuses protection changes, so this
backend registers a process-local vectored exception handler. It handles only
the verified instruction's invalid read for IDs 4–8, checks the register/index
and fault address, and resumes after the private opponent-upgrade block. Other
exceptions retain normal engine handling. The public own-upgrade path remains
intact; Windows SC2 code bytes are unchanged. Each client confirms guard setup
before gameplay; selected-player replay views with IDs 4–8 use it as well.

The Base96883 macOS observation patch is preserved separately.
Windows validation results and remaining limits are recorded in
[the three-build guide](windows-three-build-validation.md), with earlier
measurements retained in [Windows validation](windows-validation.md).
The separate [Base98370 validation](windows-98370-validation.md) covers the
updated executable. Its installed data is verified at startup; forcing
`-dataVersion` triggers an offline-chat crash in this build. If its installed
data changes, the profile refuses to run until compatible content is available.
Base75689 and Base93333 retain their required historical startup hashes.
All three profiles identify the actual ability table after joining and before
bot actions; a boot hash or replay label alone does not prove historical
balance-data parity. Per-client layouts and engine identities are recorded.

## Diagnostics

Reports are under the chosen output directory: `result.json`, per-client API
journals, `session/native-session.json`, bridge build/readiness logs, and the
optional replay. A failed run keeps its logs. Processes and ports belong to the
session; cleanup does not terminate unrelated SC2 instances.

- **Compiler missing / wrong architecture:** set `MPSC2_WINDOWS_CC` to x64
  MinGW-w64 GCC. Compiler subprocesses get its tool directory on PATH without
  modifying the parent environment.
- **Unsupported executable:** install the supported build or use standard
  one/two-player games; never substitute an arbitrary hash or macOS offsets.
- **Helper load failure:** inspect `bridge-build.log` and `bridge-error.json`.
  Antivirus restrictions may prevent process-local helper loading. The library
  does not change antivirus settings or elevate itself.
- **Startup timeout:** retain the failed directory and try a fresh one with
  fewer clients; each participant is a full game process.

`python -m mpsc2.probe` deliberately measures the **unmodified** engine and will
still report the stock 1v1 restriction. `doctor --mode standard` checks ordinary
burnysc2 games, which do not require this native helper.
