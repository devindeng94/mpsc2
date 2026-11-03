# Version metadata and native compatibility profiles

Version 0.3.2a2 separates SC2 game metadata from permission to use a native
multiplayer backend. The registries live in `src/mpsc2/versions.py`. They are
immutable Python records shipped with the package; loading them requires no
SC2 installation, network access, or PySC2 dependency.

The design follows PySC2's separation of game version, executable build and
data identifier in its [version table](https://github.com/google-deepmind/pysc2/blob/master/pysc2/run_configs/lib.py).
PySC2 passes the data identifier through
[`-dataVersion`](https://github.com/google-deepmind/pysc2/blob/master/pysc2/lib/sc_process.py).
That identifier is different from an executable SHA256 and does not authorize
MPSC2's native memory operations.

## Inspect and select a version

```powershell
python -m mpsc2 versions
python -m mpsc2 doctor --sc2-version 5.0.14
python -m mpsc2 doctor --sc2-version Base75689
```

`versions` lists known game records, native profiles, defaults and measured
support observations. It does not claim those builds are installed. `doctor`
checks the selected native profile against the local executable, compiler and
platform prerequisites. Since 0.3.2a4, Base75689 has its own native profile;
`4.10`, `4.10.0` and `4.10.0.75689` also select it on Windows.

Use the existing `sc2_version` argument to select a registered native profile:

```python
from mpsc2 import run_game

# players is a sequence of distinct Bot(..., BotAI()) instances.
results = run_game(
    "MPSC2TeamArena", players, team_ids=[0, 0, 1, 1],
    sc2_version="5.0.14", output_dir="reports/explicit-version-new",
)
```

On Windows this alias selects the exact Base93333 profile. The full label
`5.0.14.93333` and `Base93333` select it as well. macOS accepts `5.0.15`,
`5.0.15.96883` and `Base96883`. Native `GameMatch` objects and the low-level
`NativeMultiplayerSession` also accept `sc2_version`.

On an updated Base98310 Mac installation, 0.3.3a2 can
[prepare a separate Base96883 engine](macos-98310-investigation.md#prepare-the-separate-engine).
Select that root with `SC2PATH` and keep using `sc2_version="Base96883"` or the
Mac default. The restored profile uses 5.0.15 data; Base98310 is not an alias for
this compatibility engine and has no native profile.

Starting in 0.3.2a3, Windows also supports `5.0.15`, `5.0.15.98370` and
`Base98370`. The `5.0.15` alias resolves to Base98370 on Windows and Base96883
on macOS. Low-level metadata lookups should use
`get_game_version("5.0.15", system="Windows")` or an exact build; an ambiguous
lookup without an OS is rejected.

Omitting the argument preserves the existing defaults: Windows Base93333 and
macOS Base96883. Linux defaults to its separate Base75689 profile in 0.3.3a1; `4.10`, `4.10.0` and `Base75689` select it. An explicit unknown or unsupported version is refused before
game launch; it never falls back to a different build. `latest` is deliberately
not a native alias. Ordinary one/two-player games continue to delegate their
version argument to burnysc2 unchanged. Standard batch matches retain upstream
`sc2_config`; use `run_game` for a standard single-game version argument.

## What the records contain

| Record | Key | Contents |
| --- | --- | --- |
| `GAME_VERSIONS` | Exact game-version label | Build number, data identifier, explicit aliases and provenance |
| `NATIVE_PROFILES` | `(OS, executable architecture, build)` | Executable SHA256/path, working directory, backend, readiness/observation strategies, helper sources and validation evidence |
| Windows layout | Part of the native profile | Lobby/readiness addresses and expected instruction bytes; observation fault and continuation sites |
| Compatibility observations | Separate catalog entries | Tested standard API use or unverified builds; these grant no native support |

`mpsc2.versions.VERSIONS` still re-exports the original burnysc2 object. The new
`GAME_VERSIONS` and `NATIVE_PROFILES` names do not replace that compatibility API.

```python
from mpsc2 import GAME_VERSIONS, NATIVE_PROFILES

profile = NATIVE_PROFILES[("Windows", "x86_64", 93333)]
game = GAME_VERSIONS[profile.game_version]
print(game.data_version)               # SC2 launch data identifier
print(profile.executable_sha256)       # Exact executable identity
print(profile.windows_layout.lobby_state)
```

The architecture key describes the **game executable**. The existing Mac
profile remains x86_64, including an appropriate Rosetta installation. The
Windows loader requires x86_64 Windows Python as well as the x86_64 game/DLL.

## Native helper binding

Windows compilation generates `mpsc2_windows_profile.h` in the fresh session's
bridge directory. The C helper consumes the selected profile's addresses and
instruction signatures from that header. Its reports include the profile ID;
Python checks both the profile ID and owned-process PID before gameplay. The
session report records the profile, executable checksum, data identifier and
generated-header checksum. Selected-player replay guards resolve their profile
from the replay's build. Windows profiles also control the startup argument:
old engines require their boot identifiers even when a replay labels the data
with a newer installation hash; Base98370 uses verified installed data.

The macOS Base96883 helpers remain byte-for-byte unchanged. Its profile binds
their existing implementation by source SHA256, executable SHA256 and UUID.
Compilation refuses altered helper sources. The existing C files continue to
verify their own runtime instructions and implement their original readiness
and observation algorithms. A future Mac build may require a new helper/backend;
merely changing a dictionary's build number cannot adapt that legacy code.

Backend strategy names identify actual implementations. A Windows profile with
different register semantics or readiness behavior needs a compatible backend
implementation, not just replacement addresses. Only registered profiles can
be passed to helper compilation.

## Current coverage

| Target | Registry status |
| --- | --- |
| Windows Base93333 | Native 2–8-client profile; earlier live validation and registry regression checks |
| Windows Base98370 | Native 2–8-client profile; separate layout, observation strategy and installed-data launch setting; [validation](windows-98370-validation.md) |
| macOS Base96883 | Existing native profile and historical validation; unchanged C sources and offline regression checks on this machine |
| macOS Base98310 / 5.0.17 | Metadata and measured startup-failure observation only; no API Ping or native profile; [investigation](macos-98310-investigation.md) |
| Windows Base75689 / 4.10.0 | Native profile added in 0.3.2a4; separate layout and legacy ability-table translation; [three-build guide](windows-three-build-validation.md) |
| Windows Base92440 | Unverified observation only; its local directory was empty; no guessed version label/data identifier |
| Linux Base75689 / 4.10.0 | Native 2–8-client profile; [validation](linux.md) |

The Mac data identifier was not recorded in the existing evidence, so its game
record uses `None` and preserves the existing default launch behavior. The
older Windows audit found a mismatch between requested and replay-recorded
data identifiers; the registry retains that limitation instead of asserting
historically exact game-data support.

Installation diagnostics now distinguish `build_directories`,
`installed_builds` (an executable exists), and `incomplete_builds`. A detected
folder alone is no longer described as an installed executable. The standard
route still reports a missing newest build rather than silently falling back;
native launch validates its explicitly selected profile's executable.

## Adding support

1. Record the exact executable's OS, architecture, build, SHA256 and observed
   game-data identifier. Add metadata or an unverified observation first.
2. Inspect the target build's lobby, readiness and observation code. Determine
   whether an existing backend strategy applies; derive and verify its settings.
3. Add the profile and any necessary backend implementation. Preserve existing
   profiles/helpers and keep unknown binaries refused.
4. Validate native player IDs, independent ownership/actions, both timing modes,
   normal-resource research, highest-player replay views and process cleanup.
5. Record evidence, package-check the helper sources, and only then consider
   changing a platform's explicitly pinned default.

The registry organizes verified support. PySC2 metadata, version labels and
checksums cannot supply the private addresses or prove engine compatibility.

## Base98370 data selection

The profile's `data_selection="installed-verified"` omits `-dataVersion`.
On the tested installation, forcing the engine's own reported hash caused an
access violation during offline chat, including stock two-player games.
Allowing installed-data selection passed the same fixture. Every client must
report Base98370 and `84197ED58A0329FA79CC9426E07E5FB3` before CreateGame.
Replay playback checks the replay's data identifier before StartReplay, even
for the unguarded all-player view. Mismatches fail with cleanup; no historical
data fallback or additional native exception handler is used.

Other profiles retain their existing data-selection behavior and defaults.

Its `ability_remaps` table also records seven relocated engine ability IDs and
their API names. A per-client adapter translates these to/from burnysc2's IDs
for metadata, observations, queries and commands. The upstream enums are never
mutated, so older Windows and macOS clients retain their original behavior.

Since 0.3.2a4, all Windows profiles set `detect_ability_layout=True`: each client
selects a verified translation from its live API metadata before setup actions.
Base75689/93333 retain their boot arguments, and all replay views select the
matching Windows process profile. See the [three-build guide](windows-three-build-validation.md)
for why boot hashes, replay labels and live ability data are recorded separately.

## Validation of 0.3.2a2

The [dated validation record](../evidence/2026-10-31/version-registry-validation.json)
contains results and artifact hashes from this Windows machine:

- All 299 tests passed against both source and the installed wheel, including
  profile rejection, upstream export identity, native C guard behavior and
  mocked macOS 2/4/8-client handshakes.
- Explicit `Base93333` selection passed live stepped games with 2, 4 and 8
  independent clients. The installed wheel passed a four-client realtime game
  selected through the `5.0.14` alias.
- Four-player research and replay views 0 and 4 passed. Player 4 exercised the
  existing observation guard; all players received their own upgrade callbacks.
- Test-owned game processes closed, installed executable hashes stayed the same,
  and packaged sources matched the tested sources.
- Both macOS C helpers match the preceding release byte for byte. There was no
  live macOS rerun on this Windows host.
