# Windows validation

Local live validation on 2026-10-31 uses Windows 10, 64-bit Python 3.10.22,
burnysc2 7.3.0, and SC2 5.0.14 / Base93333. The installation is on a custom
drive and the checkout path contains spaces.

The stock engine probe rejects four API participants in stepped and realtime
modes and accepts two. The Windows backend was checked with independent game
processes, API ports, native player IDs, observations, actions, and replay data.

| Check | Measured result | Local evidence |
| --- | --- | --- |
| Stock CreateGame baseline | Four clients rejected in both timing modes; two accepted | `reports/windows-baseline.json` |
| Four-player 2v2 combat | Victory, Victory, Defeat, Defeat; native team ownership and replay | `reports/windows-four-05` |
| Player-count matrix | Every count 2, 3, 4, 5, 6, 7, 8 passed; distinct processes/ports/IDs, actions, movement and replay roster | `reports/windows-counts/validation.json` |
| Four-player realtime | Passed; automatic advancement and zero Step requests | `reports/windows-realtime/validation.json` |
| Four-player mixed-race research | Normal economy, production, one upgrade callback per player, native replay tracker completions | `reports/windows-research-guarded-03/research-replay-verification.json` |
| Research replay playback | All-player weapon effects and selected players 4 and 8's upgrades/events/results passed | Research replay verification records in both research directories |
| Eight-player mixed-race research | All eight completed upgrades; independent clients, no debug resource commands, owned processes closed | `reports/windows-eight-research-02/validation.json` |
| Offline regression suite | 270 passed, including compilation and execution of the actual Windows exception predicate for IDs 4–8 and refusal cases | `reports/pytest-source-final.log` |
| Installed-wheel regression suite | Same 270 tests passed outside the source checkout with imports from the workspace environment | `reports/pytest-installed-final.log` |
| Installed-wheel realtime matches | Two and four clients passed; four clients compiled/loaded the packaged helper, with zero Step requests | `reports/windows-wheel-realtime/validation.json` |

The early count-matrix and realtime runs preceded the observation guard. Their
arena fixtures do not research upgrades; the separate mixed-race runs exercise
the completed guard. Later installed-wheel checks and compact artifact hashes
are recorded in [the Windows evidence record](../evidence/2026-10-31/windows-validation.json).

## Retained failures

The unguarded four-player research run crashed in the observation serializer
for native player 4. Runtime inspection found the unsigned `3-player_id` lookup.
Direct code-page protection changes were refused by Windows; the implemented
guard instead handles only that exact invalid read and changes no SC2 code
bytes. The guarded run completed, and its per-client report confirms the fault
was encountered and handled.

That completed four-player run's original `validation.json` still says failed:
the old post-game `os.kill(pid, 0)` check raised Windows error 87. The validation
scripts now use psutil and account for recycled PIDs. The independent replay
verification passed; the historical failure record is not rewritten.

The first eight-player research launch timed out at the 90-second join barrier
with six of eight readiness events (`reports/windows-eight-research`). Its
fresh retry passed. Startup reliability remains an alpha limitation; a passing
retry does not explain the initial timeout. Earlier compiler lookup, socket
hook and readiness-hold failures also remain under local `reports/`.

## macOS preservation and scope

The macOS C helpers are byte-identical to the downloaded source. AST comparison
also confirms the native Python functions/classes are unchanged after removing
the new Windows dispatch branch. UUID/hash checks, launch arguments, and the
macOS replay guard remain intact. Offline regression tests exercise macOS
dispatch and guard behavior. No macOS game was launched here; live macOS
regression remains a separate check on a Mac with the supported build.

Support remains experimental and exact-build-specific. These checks do not
establish compatibility with every Windows SC2 release, arbitrary custom maps,
remote multiplayer hosts, or long training campaigns.
