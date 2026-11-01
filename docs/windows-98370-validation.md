# Windows SC2 5.0.15 / Base98370

This records the 0.3.2a3 port. The [0.3.2a4 three-build guide](windows-three-build-validation.md)
adds Base75689 and rechecks Base93333 and Base98370 with live ability-table detection.

MPSC2 0.3.2a3 adds a separate profile for the updated Windows executable.
Select it with `sc2_version="5.0.15"`, `"5.0.15.98370"` or `"Base98370"`.
The existing Windows Base93333 and macOS Base96883 defaults are retained.

## Target and changes

- Windows x86_64, SC2 `5.0.15.98370`.
- Executable SHA256:
  `c68202849f8e64ed20d15bea0fb89f2c5b94028d075d9848e124a8264d130222`.
- API and replay data identifier: `84197ED58A0329FA79CC9426E07E5FB3`.
- Profile: `windows-x86_64-98370-v1`.

The stock engine still rejects more than two API participants. Its lobby state,
roster and readiness addresses moved; the original Windows signatures do not
match. The new profile supplies verified addresses and instruction signatures.
The two-slot readiness hold and loopback discovery strategy are retained.

The private opponent-upgrade serializer still uses unsigned `3-player_id`,
but stores the player ID on the stack and uses different registers. The new
guard checks the exact read fault, saved player ID, index, table address and
constant before skipping that private field. It preserves the public own-upgrade
path. The earlier Windows guard remains a separate compile-time strategy.

## Ability table compatibility

The first economy test stopped with `KeyError: 4135`: the gas-worker order
`WorkerStopIdleAbilityVespene/Gather` moved from python-sc2 ID 4132 to engine
ID 4135. Seven existing ability entries moved after three new slots appeared.
The profile records explicit mappings verified against API link/button names:

| Ability | Engine ID | burnysc2 7.3.0 ID |
| --- | --- | --- |
| Morph Baneling | 4124 | 4121 |
| Cancel Baneling morph | 4125 | 4122 |
| Mothership cloak | 4127 | 4124 |
| Energy recharge | 4129 | 4126 |
| Salvage effect | 4131 | 4128 |
| Sensor tower salvage | 4133 | 4130 |
| Worker gas gather | 4135 | 4132 |

The per-client adapter normalizes metadata, orders and ability queries, and
translates outgoing commands/placement queries back to engine IDs. It leaves
upstream enums, other clients and caller-owned protobuf objects unchanged.
Metadata-name mismatches and unmapped IDs that collide with the Python table
are rejected. The retained failed run is `reports/build98370-research-four`.
This validates the observed compatibility problems; every ability and newly
introduced spell is not covered by the live fixtures.

## Installed-data requirement

On this installation, explicitly passing the correct `-dataVersion` caused a
null read during startup chat, including a stock two-player game. Removing
optional player names did not fix it. Omitting that flag passed the same
two-player and four-player fixtures with the expected data identifier.

The new profile therefore selects installed data and checks API Ping on every
client before creating the game. Both build and data identifier must match.
Replay playback performs the same check against replay metadata before
StartReplay, including observer zero. A later installation update that changes
the loaded content is rejected. This profile does not promise historical data
selection through `-dataVersion`.

No extra native exception handler hides this chat fault. Installed game files
are unchanged. The failed diagnostic runs remain local under
`reports/build98370-two-profile`, `reports/build98370-two-no-name`,
`reports/build98370-four-01` and `reports/build98370-four-diagnostic`.

## Reproduce

```powershell
python -m mpsc2 doctor --sc2-version 5.0.15
python scripts/validate_player_counts.py --sc2-version Base98370 --counts 2 3 4 5 6 7 8 --output reports/new-build-counts
python scripts/validate_player_counts.py --sc2-version Base98370 --counts 4 8 --realtime --output reports/new-build-realtime
python scripts/validate_alpha.py --phase races --sc2-version Base98370 --research-only --output reports/new-build-research
python scripts/verify_research_replay.py reports/new-build-research --playback
```

Use fresh output directories. Research uses normal resources and production;
the validation checks that no debug requests are sent. Live macOS testing is
not possible on this Windows host; both Mac helper source hashes and the
mocked Mac session regressions are checked instead.

## Measured results

- Every stepped arena count from 2 through 8 passed with independent process,
  API port, native player ID, unit ownership and movement checks.
- Mixed Terran/Protoss/Zerg/Random research passed at 4 and 8 players with
  normal mining, construction, army production and exactly one expected
  upgrade callback per player. No debug requests were used.
- Replay tracker events confirm every player's research. Playback passed for
  all-player view 0 and highest-player views 4/8, including own upgrade
  callbacks and visible weapon-upgrade effects. Affected player IDs exercised
  the native observation guard.
- All 321 tests passed against source and the installed wheel, including both
  compiled Windows fault-handler predicates, protocol translation, unchanged
  enum identity, metadata mismatch rejection and replay startup cleanup.
- Realtime arena games passed at 4 and 8 players with zero Step requests. The
  installed wheel also passed a four-player realtime game outside the source
  checkout. All test-owned game processes closed.
- The unchanged Base93333 native profile passed a four-player arena regression.
  Its replay identified the old engine but the newly installed data hash
  `84197ED58A0329FA79CC9426E07E5FB3`, despite requesting its historical hash.
  This verifies the older native handshake, not historical 5.0.14 content or
  research compatibility with the updated data. Use Base98370 for this updated
  installation's economy/research workloads.

The raw runs are retained under `reports/build98370-*` locally. Installed
executables, game data and upstream Python packages are not patched.
The [dated evidence record](../evidence/2026-11-01/windows-98370-validation.json)
contains measured results, retained failures and artifact hashes.
