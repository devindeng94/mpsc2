# Four independent clients: successful 2v2 prototype

Historical record of the 2026-10-28 prototype. For current APIs and the later
research fix, see the [current documentation](../../docs/README.md). Raw data
under `four-client-success/` remains local-only; its [hash manifest](four-client-success/sha256.json)
is public. This publication note does not change the measured results below.

On 2026-10-28, four independent SC2 processes successfully ran the same 2v2
combat game through four `python-sc2` Clients. This supersedes the earlier
conclusion that only a two-player launch had been achieved. The stock API still
rejects four participants; a local native bridge now completes the missing
host/discovery/start behavior.

## Reproduce

From the repository root, with this Mac's Base96883 installation:

```sh
.venv/bin/python -m mpsc2.smoke --experimental-native-four \
  --output reports/new-four-player-run
.venv/bin/python -m mpsc2.smoke --experimental-native-four --fog \
  --output reports/new-four-player-fog-run
```

Use fresh output directories. The Python launcher compiles and loads the bridge
automatically. It reports failures explicitly and never substitutes computer
players or one shared controller. All SC2 processes are owned and cleaned up by
the session. Source: [Python launcher](../../src/mpsc2/native_session.py),
[native bridge](../../src/mpsc2/native/local_four_bridge.c),
[smoke test](../../src/mpsc2/smoke.py).

## Measured success

| Property | Full visibility | Normal fog |
| --- | --- | --- |
| SC2 process IDs | 4922, 4959, 4995, 5025 | 5256, 5292, 5320, 5342 |
| Native player IDs | 1, 2, 3, 4 | 1, 2, 3, 4 |
| Roster on every client | Four Participants | Four Participants |
| Initial units per perspective | Six from every owner | Six own + six allied; no enemies |
| Own movement | Six units per player | Six units per player |
| Other-owner commands | `YouCantControlThatUnit` (87), zero movement | Same |
| Active observations checked for matching frames | 32 | 30 |
| Final reported frames | 352, 352, 352, 352 | 337, 337, 336, 336 |
| Results on every client | Victory, Victory, Defeat, Defeat | Same |
| CLI exit | 0 | 0 |

The fog run's final observations differ by one frame as clients enter the ended
state. Their observations matched throughout active play; terminal result
dictionaries agree exactly. Do not interpret final-frame equality as a property
established for every episode.

Teams are native player IDs 1+2 and 3+4. Guest process order is not an identity:
the earlier raw-protocol success returned `[1, 4, 3, 2]`. The session returns the
mapping rather than assuming it.

The terminal policy is deliberately asymmetric: team A attacks, team B moves.
It uses normal raw unit commands on all four independent clients, with no debug
kill or hidden computer AI. It verifies control and team results, not policy
quality or balanced gameplay.

The replay metadata independently lists players 1–4 with two Win and two Loss
results. Full replays are local under `reports/python-sc2-four-terminal/` and
`reports/python-sc2-four-fog/`. The test verifies nonempty replay bytes and their
metadata; replay playback itself has not been validated. `sc2reader`'s full
loader encountered an empty cache-handle list on these local-session replays;
the MPQ metadata is readable independently.

## Why the previous attempts stopped at two

Read-only inspection of the installed build identified three separate limits in
the API launch path:

1. Four `PlayerSetup` entries are parsed into the engine's internal roster before
   `CreateGame` returns its explicit 1v1 error. The successful handler would then
   set the host flag and transition from launched to init_game. The bridge makes
   those two DATA writes only after checking the exact rejected request's state,
   participant count, roster types, engine UUID and expected original code bytes.
2. Although JoinGame accepts a repeated port field, this launch path selects the
   first guest pair. The local UDP discovery sender therefore reaches one guest.
   Host-side `sendto` interposition copies those loopback datagrams to the other
   two configured UDP ports. All three guests then establish native connections.
   On this build the protobuf `game_port` is the UDP discovery port and
   `base_port` is the TCP listener, as confirmed with live sockets.
3. The API host starts automatically when its readiness sum equals two. The
   bridge temporarily adds a sentinel in an unused readiness slot before any
   guests join. It waits for four real readiness events, then satisfies that
   start predicate without deleting anyone from the native four-user roster.

Only the host loads the bridge. Guests use the original executable normally.
The Python package continues to send the existing protobuf requests through
four actual `sc2.client.Client` objects. There are no invented protocol fields,
observer substitutes, or consolidated policy controllers.

This is a prototype based on inspected runtime internals, not a supported
Blizzard extension. The guarded DATA writes include a polling-based readiness
transition; extensive stress tests and a more formal native adapter remain
future engineering work. The bridge writes no executable instructions and
does not edit or re-sign the installed SC2 application.

## Additional map fix

Initial multiplayer combat tests reached a late failure: a client returned to
`launched`, so the next step failed before terminal results were readable.
Changing the map's call from `GameOver(p, result, false, false)` to
`GameOver(p, result, true, false)` retained the terminal game state. Both full
visibility and fog tests then returned normal `ended` observations with the
shared results. The earlier debug-elimination failure alone did not establish
that debug commands caused desynchronization; the successful final test uses
ordinary combat commands.

The [Galaxy function reference](https://mapster.talv.space/galaxy/reference/game-over)
documents the dialog parameter and includes Blizzard's own Galaxy call sites.
The before/after behavior above was measured locally.

## Evidence and boundaries

Original raw evidence is local under `four-client-success/`, with a public
[SHA256 manifest](four-client-success/sha256.json). The local files include the first successful raw protobuf requests and
responses, readiness/fanout records, the two successful Python reports, per-client
request/status journals, launch arguments and replay metadata/checksums. It does
not include proprietary code or memory snapshots. Earlier failed reports and
superseded experimental helpers were removed during workspace cleanup; the
successful evidence and the two full validation runs remain intact.

The tested executable is macOS x86_64 SC2 5.0.15.96883:

- SHA256: `7a8e076ce304d6cc18591eed03bda5ea68a8639826c0b7364de3f53a3da8e0eb`
- Mach-O UUID: `DA36F25F-C234-30EB-BE05-E4BC16017B08`
- Data version: `B49DA51995BA9767F4C624034C211342`
- Final map SHA256: `5067d76a0ba49bf93ab8aca43011d79955da65d0bbfcc2c32ef08088fdf02af8`

The Python layer checks the executable hash before launching. The native helper
checks the UUID and runtime preconditions. Other builds/platforms and remote
hosts have not been validated. This map has combat units but no economy or
production. Four BotAI lifecycles, training, episode reset/throughput, full melee
maps and sustained reliability are follow-on work; the requested four-client
launch and independent 2v2 control milestone is achieved.

Public references that initially described the narrower API remain accurate for
the stock interface: [Blizzard's schema](https://github.com/Blizzard/s2client-proto/blob/master/s2clientprotocol/sc2api.proto),
[multiplayer flow](https://github.com/Blizzard/s2client-proto/blob/master/docs/protocol.md),
and [more-than-two-agent issue](https://github.com/Blizzard/s2client-proto/issues/60).
They do not rule out the native bridge demonstrated here.
