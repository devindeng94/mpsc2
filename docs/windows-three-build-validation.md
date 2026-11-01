# Windows Base75689, Base93333 and Base98370

MPSC2 0.3.2a4 registers separate native profiles for all three installed Windows
x86_64 executables. This supports bundled MPSC2 scenarios with independent
clients; it does not add arbitrary multiplayer maps or remote hosts.

| Exact selector | Engine version | Startup data selection | Observation strategy |
| --- | --- | --- | --- |
| `Base75689` / `4.10` | 4.10.0.75689 | Historical boot hash `B89B5D6FA7CBF6452E721311BFBC6CB2` | Verified R14/RCX/RBX fault predicate at its own addresses |
| `Base93333` / `5.0.14` | 5.0.14.93333 | Historical boot hash `446907060311FB1CC29EB31E547BB9FD` | Existing R14/RCX/RBX predicate |
| `Base98370` / `5.0.15` | 5.0.15.98370 | Installed data, verified API identity; no explicit data flag | Existing stack/RAX/RDI predicate |

The executable hashes are recorded in `mpsc2.versions.NATIVE_PROFILES` and
checked before launching a helper. Every running client must report the
selected base build. No selection falls back to a newer executable. The
omitted-argument Windows default remains Base93333; macOS remains Base96883.

## Engine, boot hash and live data

These identify different things. On this machine, an older executable can
echo its requested boot hash in Ping while its replay labels the data with the
current installation's hash. Base75689 nonetheless exposes a legacy ability
table ending at ID 3800. Neither the launch hash nor the replay label alone
certifies historical balance rules or identical content across engines.

Windows clients now request actual game data after joining and before setup or
bot actions. The adapter recognizes three verified tables by API link/button
names, rather than guessing from the executable version:

- Legacy 4.10: four rock-tower ability IDs 3797–3800 translate to the
  corresponding burnysc2 IDs 3966/3967/3969/3970.
- Canonical table: the seven later abilities match burnysc2 7.3.0 directly.
- Shifted table: those seven entries use the Base98370 mappings documented in
  [the previous build report](windows-98370-validation.md).

Each client owns its translation. Upstream enums are unchanged. Unknown or
changing layouts are rejected, and outgoing IDs that would select unrelated
abilities are refused. Session reports contain `ability_layouts` and each
process's API-reported engine/data identity. This supports measured gameplay
on the installed versions; it does not promise historical data-package parity
or every ability added after an older engine was released.

## Replay handling

All registered Windows replay views launch the replay's exact engine profile.
Older engines use their required boot hashes instead of blindly passing the
replay's installation-derived label. The live ability table is inspected again
before observation callbacks. Views 4–8 load the matching native guard; view 0
does not load a guard. Base98370 retains its installed-data mismatch check.

## Measured results on 2026-11-01

Windows 10 x64, Python 3.10.22, burnysc2 7.3.0 and MPSC2 0.3.2a4:

| Engine | Stepped arena counts | Realtime arena counts | Mixed-race research | Replay playback |
| --- | --- | --- | --- | --- |
| Base75689 | 2, 3, 4, 5, 6, 7, 8 passed | 4 and 8 passed | 8 players passed | Views 0 and 8 passed |
| Base93333 | 2, 3, 4, 5, 6, 7, 8 passed | 4 and 8 passed | 8 players passed | Views 0 and 8 passed |
| Base98370 | 2, 3, 4, 5, 6, 7, 8 passed | 4 and 8 passed | 8 players passed | Views 0 and 8 passed |

The arena fixtures use a five-second game limit and check independent native
IDs, processes, ports, unit ownership, team mapping, actual movement commands,
callbacks, replay rosters and native results. Realtime journals contain no
`Step` requests. These are bounded integration checks, not long-run benchmarks.

The research fixture uses eight Terran/Protoss/Zerg/Random bots, a 500-second
configured limit and step size 32. Every bot mined resources, produced workers
and combat units, built production/gas structures and completed its expected
upgrade with exactly one own-upgrade callback. There were zero `Debug` requests.
For every build, the native guard handled the verified invalid opponent lookup
for IDs 4, 5, 6, 7 and 8. Replay tracker events and playback confirmed the
upgrades; observer zero also confirmed the visible weapon-level effects.

All **334 offline tests passed against both source and the installed wheel**,
including all three native guard predicates and client-isolated ability tables.
The installed wheel also passed a separate four-player realtime game on each
of the three builds from outside the source checkout. All 87 packaged files
match the tested source, including the native helper and map assets.
The installed package's `doctor` passed for all three exact executables, and
`pip check` reported no broken requirements.

The [public evidence record](../evidence/2026-11-01/windows-three-build-validation.json)
contains build identities, native IDs, detected layouts and local artifact
hashes. Raw reports and replays remain local. The initial no-data-flag
Base75689 launch did not connect, and the first four-client run rejected its
then-unknown ability table; both attempts are retained with their resolutions.
Historical balance parity, every ability and long training campaigns remain
outside this validation.

## Reproduce

```powershell
python -m mpsc2 doctor --sc2-version Base75689
python -m mpsc2 doctor --sc2-version Base93333
python -m mpsc2 doctor --sc2-version Base98370
python examples/multiplayer.py --players 8 --sc2-version Base75689 --output reports/legacy-eight-new
```

Select any of the three builds using the same Python API:

```python
from mpsc2 import run_game

# players contains four distinct Bot(..., BotAI()) instances.
results = run_game(
    "MPSC2Melee", players, team_ids=[0, 1, 0, 1],
    sc2_version="Base93333", output_dir="reports/exact-build-new",
)
```

The validation commands are `scripts/validate_player_counts.py` with
`--sc2-version Base<number>`, `scripts/validate_alpha.py --phase races` with
the same selector, and `scripts/verify_research_replay.py <research-folder>
--playback`. Use fresh output directories for every run.

The eight-player research fixture uses `--research-only --step-size 32 --races
Terran Protoss Zerg Random Terran Protoss Zerg Random`. Replay verification
checks both observer zero and the highest native player ID.

Both macOS helper source hashes are preserved. The Mac dispatch and protocol
passthrough regressions are checked offline; no live Mac rerun is possible on
this Windows host.
