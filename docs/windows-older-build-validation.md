# Older Windows build compatibility audit

Tested on 2026-10-31 using the existing Windows installation, Python 3.10.22,
burnysc2 7.3.0, and MPSC2 0.3.2a1. This audit adds no supported native build.

## Installation correction

The machine contains `Base75689`, not `Base75698`. `Base92440` is an empty
directory: it contains neither `SC2_x64.exe` nor `SC2.exe`. The earlier
installation listing inferred available builds from directory names and
overstated Base92440's availability. No other Base92440 executable was found
under the SC2 installation or the local GitHub project directory.

| Build | Ordinary two-player API | Native MPSC2 3–8-player backend |
| --- | --- | --- |
| Base75689 / SC2 4.10.0 | Passed the checks below | Incompatible with the current Base93333 bridge; a separate verified profile is required |
| Base92440 | Not tested: executable missing | Not tested: executable missing |
| Base75698 | No such installed directory | No such installed directory |

## Base75689 measurements

The executable SHA256 is
`b7cac088c463c64ce5ac84acafba546c8c2c13cb7df3613a9c09fb9b0e61f7f9`.
API Ping and replay metadata both identify the running engine as
`4.10.0.75689`; these results did not come from a fallback to Base93333.

- The production Windows executable validator rejects this hash, as intended.
- Stock CreateGame rejects four API participants in both stepped and realtime
  modes with `Only 1v1 is supported when using multiple agents` (error 7).
- Stock CreateGame accepts two API participants.
- Read-only inspection after API startup found that **all five** instruction
  signatures checked by the Base93333 helper differ at their expected relative
  addresses: lobby validation, readiness, private opponent-upgrade lookup,
  public own-upgrade lookup, and the guard's cleanup destination. The native
  helper was not loaded, and game memory was not written by the audit.
- A test-only launcher selected the exact older executable without loading any
  helper. The existing MPSC2 BotAI orchestration then completed two-player
  arena games in stepped and realtime modes. Both clients issued actions,
  moved their own units, observed native Tie results, saved a replay, and
  closed. Processes, API ports and player IDs were distinct. Stepped journals
  contain 13 Step requests per client; realtime journals contain zero.
- A separate test used the **unchanged public** `run_game_async` standard-game
  route on `Melee/Simple64.SC2Map` with `sc2_version='4.10'`. Both bots received
  observations, issued movement commands, advanced for 15 callbacks, and
  closed. This bounded test stopped at its time limit: its Python Tie results
  are timeout results, while the saved standard-game replay says Undecided.

These distinguish reusable Python/API code from the incompatible native
multiplayer bridge. The test-only launcher is not an enabled production route
for older bundled multiplayer scenarios. The public API's `sc2_version`
argument applies to ordinary games; bundled native multiplayer currently
refuses that override and selects Base93333.

## Data-version limitation

Launch arguments explicitly requested 4.10's data hash
`B89B5D6FA7CBF6452E721311BFBC6CB2`, and API Ping echoed that value. However,
all three saved replays contain DataVersion
`446907060311FB1CC29EB31E547BB9FD`, the current installation's data version,
while still reporting Base75689 and GameVersion 4.10.0.75689. The reason for
this discrepancy was not established. The tests verify this older **engine**
against the machine's installed data; they do not establish historically exact
4.10 balance data or successful replay playback.

## Reproduction and evidence

Run from the source directory with its dependencies installed, using a fresh
output directory:

```powershell
$env:SC2PATH = 'E:\StarCraft II'
python scripts/audit_windows_builds.py --builds 92440 75689 --output reports/older-build-audit-new
```

The script never authorizes an unknown build for native memory changes. It
records missing executables, checks the existing production validator, launches
available builds through the stock API, inspects instruction signatures, and
tests two-player shared orchestration.

The compact [evidence record](../evidence/2026-10-31/windows-older-build-validation.json)
contains findings and artifact hashes. Raw local evidence is in
`reports/older-build-audit-01`, including the separate standard-route script,
API journals, engine reports and three replays. Game executable hashes are
unchanged, and the audit's owned processes were closed. Production native
backends and the existing release wheel were not modified.

Base92440 needs a complete matching installation before any compatibility
conclusion can be drawn. Base75689 needs analysis and validation of its own
native lobby/observation implementation before 3–8-player support can be added.
