# Engineering history (through 0.1)

This is the original implementation and validation record. For the current API,
installation and support matrix, see [the README](../README.md) and
[API reference](api.md). Paths under `reports/` refer to local, ignored artifacts.
Raw prototype evidence is also local-only; public summaries and hashes are
listed in the [evidence index](../evidence/README.md). The descriptions of a
data-only, four-client bridge below describe 0.1, before the later observation fix.

# MPSC2: multiplayer self-play with four independent SC2 clients

**Four-client combat and full economy games work.** Four separate StarCraft II processes, each
with its own `python-sc2` Client and WebSocket, join one game as native players
1–4. Teams follow the supplied `team_ids`. Each client observes and commands
its own player; teammates share vision without sharing unit control.

This is an **experimental, build-specific native bridge**, alongside the Python
launcher. It is not stock API support or a Python-only fix. Tested on macOS with
SC2 **5.0.15.96883**, Python 3.13.2, and `burnysc2==7.3.0`. The installed game
executable is unchanged. The host loads a project-built library that makes
guarded changes to its own runtime data and forwards local discovery datagrams.

## Run the working test

Python **3.10 or newer** is required. Install from `pyproject.toml` as below so
pip selects dependencies compatible with your Python version. The pinned
`requirements-lock.txt` records the original Python 3.13.2 environment.

Run from this repository, with SC2 installed and Apple's command-line compiler
available. Set `SC2PATH` if the installation is somewhere other than
`/Applications/StarCraft II`. Choose a fresh output directory for every run.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python scripts/build_map.py

# Four independent python-sc2 clients: alliances, ownership, movement and combat.
.venv/bin/python -m mpsc2.smoke --experimental-native-four \
  --output reports/my-four-player-test

# Repeat with normal fog and shared teammate vision.
.venv/bin/python -m mpsc2.smoke --experimental-native-four --fog \
  --output reports/my-four-player-fog-test
```

The command compiles the host bridge, starts four local SC2 windows, waits for
four native lobby readiness events, runs the checks, saves replays and closes
only its own processes. Exit 0 means all requested checks passed. No Battle.net
lobby, account, or external player is involved.

## Full economy game

[`examples/full_game.py`](../examples/full_game.py) runs four Terran `BotAI`
instances on [`maps/MPSC2Melee.SC2Map`](../maps/MPSC2Melee.SC2Map), with normal fog
and shared teammate vision. Each starts with **12 SCVs, one Command Center,
50 minerals, zero gas and no army**. The bots mine minerals and gas, construct
Supply Depots, Barracks, Refineries and Tech Labs, train SCVs, Marines and
Marauders, build a second Command Center, and attack enemy bases. Production
uses ordinary python-sc2 commands and normal costs and construction times.

```sh
# Use a fresh output directory for each match.
.venv/bin/python examples/full_game.py --teams 7 9 7 9 --output reports/my-economy
.venv/bin/python examples/full_game.py --realtime --teams 7 9 7 9 --output reports/my-realtime-economy

# Independent replay verification; requires the dev extra.
.venv/bin/python scripts/verify_economy_replay.py reports/my-economy

# Rebuild the checked-in map from its source.
.venv/bin/python scripts/build_melee_map.py
```

The example uses the same public `run_game` API, changing the map and bot class,
with `game_time_limit=900`. Use `--teams 0 0 0 1` for 3v1 or
`--teams 0 1 2 3` for free-for-all. The full economy live validation covers
2v2; the earlier combat validation covers all three layouts.

The map has four starting bases and four expansion sites on flat terrain,
each with eight 1,800-mineral fields and two 2,250-gas geysers. It initializes
race-specific starting units through SC2's native melee functions. The supplied
macro bot and full economy validation use Terran. A team loses when **all its
buildings** have been destroyed; surviving teammates can continue after losing
one player's base. All four clients receive native results together. The timer
returns a draw if multiple teams remain. This is a custom economy fixture, not
a ladder map or a benchmark of policy strength.

Each output directory contains:

- `game.SC2Replay` and its exact `game.SC2Map`.
- `result.json`: team assignments, four process/port identities and native results.
- `player-0.json` through `player-3.json`: engine resource scores, observed
  construction events, trained units and periodic economy snapshots.
- `economy-summary.json`: per-player checks for collection, spending,
  construction, production, expansion and combat. The example exits nonzero if
  these checks fail. Counts are from each bot's last active observation.
- `replay-verification.json`, after running the verifier: independent tracker
  births, construction completions and durations, final results, four-client
  identity checks and absence of debug requests. In realtime it also verifies
  that there were no manual step requests. Replay tracker counts include final
  frames that callbacks can miss.

The replay verifier reads the tracker stream directly because local API replays
have no Battle.net cache handles, which sc2reader's full lobby loader expects.
It does not need a Battle.net account or network access.

Validated stepped evidence is saved under
`reports/economy-2v2/`, including the
economy checks (`reports/economy-2v2/economy-summary.json`) and
replay checks (`reports/economy-2v2/replay-verification.json`).
The final realtime validation is under
`reports/economy-realtime-2v2/`, with its
replay (`reports/economy-realtime-2v2/game.SC2Replay`) and
verification (`reports/economy-realtime-2v2/replay-verification.json`).
Both runs used interleaved teams `[7,9,7,9]` and returned
`[Victory, Defeat, Victory, Defeat]` in input order. The stepped run used
Python 3.13; the realtime run used Python 3.10 and the final resource-snapshot
cleanup. The realtime match continued after one player lost all its buildings,
until its teammate was also defeated.

In the realtime run, all four players completed at least five Supply Depots,
two Barracks, a Refinery, a Tech Lab and an expansion Command Center. The
independent replay tracker recorded:

| Input player | Team | Minerals / gas collected | Additional SCVs | Marines | Marauders | Result |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 7 | 7,960 / 772 | 33 | 15 | 13 | Victory |
| 2 | 9 | 4,250 / 552 | 16 | 8 | 9 | Defeat |
| 3 | 7 | 8,025 / 764 | 33 | 15 | 14 | Victory |
| 4 | 9 | 6,230 / 724 | 30 | 12 | 12 | Defeat |

Collection totals come from the last active engine observations; unit counts
come from the replay. Both matches used four native participants and no debug
requests. The realtime journals contain **zero step requests**. Compact results,
checksums and environment details are retained in
[`evidence/2026-10-29/full-economy-validation.json`](../evidence/2026-10-29/full-economy-validation.json).

## Verified behavior

The full-visibility run is recorded in
`reports/python-sc2-four-terminal/result.json`.

| Check | Observed result |
| --- | --- |
| Independent processes and API clients | Four distinct PIDs and WebSocket ports |
| Native participants | Four distinct IDs; all four rosters contain Participants 1–4 |
| Team alliances | Every perspective sees Self, Ally, and two enemy owners correctly |
| Separate control | Each player moved all six of its own Marines |
| Unauthorized unit commands | Rejected with action result 87; zero position change |
| Simulation synchronization | All four at loop 72 after movement and loop 352 at termination |
| Native team results | Every client reports `{1: Victory, 2: Victory, 3: Defeat, 4: Defeat}` |
| Replay metadata | Four player IDs and two wins/two losses |

The terminal fixture uses ordinary synchronized commands: team A attacks and
team B moves through its firing line. This verifies the game's result handling;
it is not a benchmark of learned policies. The terminal replay is
`reports/python-sc2-four-terminal/smoke.SC2Replay`.
The fog run is saved separately under `reports/python-sc2-four-fog/`.

The first breakthrough used direct protobuf/WebSocket requests, without
`python-sc2` or `pysc2`: four distinct IDs, six moved units each, and all four
simulations at loop 40. Its raw request/response evidence is retained locally under
`evidence/2026-10-28/four-client-success/`; the public checkout includes its
[hash manifest](../evidence/2026-10-28/four-client-success/sha256.json).
See the [engineering account](../evidence/2026-10-28/four-client-success.md) for the
mechanism, experiments and scope of the evidence.

## What makes four clients work

The stock engine rejects a four-participant `CreateGame` with
`InvalidPlayerSetup: Only 1v1 is supported when using multiple agents`.
Blizzard's [protocol schema](https://github.com/Blizzard/s2client-proto/blob/master/s2clientprotocol/sc2api.proto)
also describes only one guest for `client_ports`. Adding repeated protobuf
entries alone did not fix the behavior.

The installed engine nevertheless has a native multiplayer lobby and simulation
that can run all four participants. Three changes bridge the API's narrower
launch path to that capability:

1. After the rejected request has populated a verified four-slot roster, perform
   the successful host handler's two runtime-data state transitions.
2. Forward the host's loopback UDP discovery traffic from the first guest's
   configured discovery port to the other two guests. Each guest receives its
   own local port pair.
3. Hold the API's automatic start condition until four actual native readiness
   events have arrived. Then allow the native four-user game to start.

The bridge does not modify executable instructions, modify the installation,
create computer-controlled substitutes, or merge policies into one client.
The map also uses `GameOver(..., true, false)` so terminal observations remain
available; hiding the end dialog caused multiplayer clients to return to the
launcher before results could be read.

## Python interface

`mpsc2.run_game` accepts ordinary `sc2.player.Bot` / `BotAI` instances and a
required `team_ids` list. Both team assignments and returned `sc2.data.Result`
values follow **the input player order**, regardless of native join order.

```python
from pathlib import Path
from sc2.data import Race
from sc2.player import Bot
from mpsc2 import run_game
from examples.team_game import MarineBot

results = run_game(
    Path("maps/MPSC2TeamArena.SC2Map"),
    [Bot(Race.Terran, MarineBot(), name=f"bot-{i}") for i in range(4)],
    realtime=False,
    team_ids=[10, 10, 20, 20],
    random_seed=7,
    disable_fog=False,
    save_replay_as="reports/my-match/game.SC2Replay",
    output_dir="reports/my-match",  # must not already exist
)
print(results)
```

Equal team IDs cooperate; different IDs compete. IDs may be any integers.
Use `[0, 1, 2, 3]` for free-for-all, `[0, 0, 0, 1]` for 3v1, or
`[0, 1, 0, 1]` for two interleaved teams. Teammates share vision and native
victory/defeat, while retaining separate unit control.

The executable example accepts all these layouts:

```sh
.venv/bin/python examples/team_game.py --teams 0 0 1 1 --output reports/my-2v2
.venv/bin/python examples/team_game.py --teams 0 0 0 1 --output reports/my-3v1
.venv/bin/python examples/team_game.py --teams 0 1 2 3 --output reports/my-ffa
```

Set `realtime=True` to let the engine advance automatically. A minimal 2v2
example is [`examples/minimal_realtime.py`](../examples/minimal_realtime.py):

```sh
.venv/bin/python examples/minimal_realtime.py

# Or use the configurable example, with a saved replay:
.venv/bin/python examples/team_game.py --realtime --teams 0 0 1 1 --output reports/my-realtime
```

In this mode, the launcher sends `CreateGame(realtime=True)`. Each bot runs its
own observation/callback loop and requests future observations using the
protocol's [`RequestObservation.game_loop`](https://github.com/Blizzard/s2client-proto/blob/master/s2clientprotocol/sc2api.proto)
field. The runner sends **no `RequestStep` messages**, and observations from
different clients need not have identical frame numbers. An async callback
waiting on one client does not stop the other clients' loops. All policies
share one Python event loop, so blocking synchronous computation should be
offloaded rather than performed inside callbacks.

Realtime armies spawn paused for startup and alliance checks. After all four
`on_start` callbacks finish, each client declares readiness; the map unpauses
the armies and starts the match timer. Thus initialization time does not consume
`game_time_limit`. SC2's absolute game loop, and therefore `BotAI.time`, still
includes this startup interval.

[`run_game`](../src/mpsc2/main.py) follows the startup and callback order in
`burnysc2==7.3.0`: `on_before_start`, `on_start`, event callbacks, `on_step`,
action flushing, and `on_end`. Each bot has its own SC2 process, Client and
WebSocket. Four policies execute concurrently in the calling Python process.
Use `await run_game_async(...)` from notebooks or an existing asyncio loop.

Before `on_before_start`, each bot receives these additional attributes:

| Attribute | Meaning |
| --- | --- |
| `player_index` | Zero-based index in the input `players` list |
| `player_id` | Actual native SC2 player ID |
| `team_id` | This bot's input team label |
| `team_ids` | Mapping from native player ID to input team label |
| `ally_player_ids` | Native IDs of teammates, excluding self |
| `enemy_player_ids` | Native IDs of opposing players |
| `player_start_locations` | Economy map only: native player ID to known starting-base `Point2` |

`self.units` contains only owned units; `self.enemy_units` excludes teammates.
Visible allied units are available through `self.all_units` (alliance value 2)
or raw observations. Upstream's singular `enemy_race` remains `None` in a
four-player match; use the player roster for multiple opponents.

The implementation supports **exactly four bots**, either realtime mode, and
the checksum-pinned `maps/MPSC2TeamArena.SC2Map` and `maps/MPSC2Melee.SC2Map`. It generates a separate map
copy containing team setup and victory rules; it does not alter the input map.
A setup chat from each client binds its input slot to the native triggering
player. Armies spawn only after all four declarations, and alliances are
verified before bot callbacks begin. This handles guest IDs such as `[1,4,3,2]`
without moving policies, names, or races between clients.

This is a subset of upstream `run_game`, not a drop-in replacement for every
option. Human/Computer players, external bot processes, fullscreen,
arbitrary melee maps, custom port configurations and other SC2 builds are not
supported by this entry point yet. The arena always supplies six Marines per
player, independent of the selected race; use the economy map for starting bases
and normal production. The economy map exposes opponents' known starting
positions through `enemy_start_locations`; it does not reveal hidden enemy units.
The runner removes stale neutral-resource snapshots co-located with visible
resource nodes before constructing `GameState`. This prevents Base96883's
duplicate snapshots from breaking python-sc2's expansion finder. Raw protocol
responses remain intact.

With `realtime=False`, `step_size=8` controls the synchronized simulation step;
all four bots must use the same `client.game_step`. With `realtime=True`, it
controls initial observation spacing; bots may choose different
`client.game_step` values. Values must be integers in 1..224 in either mode.
The engine keeps advancing during realtime decisions, so a slow bot can skip
observation frames. Bots must not advance, restart or leave the simulation
themselves. `game_time_limit=120` sets a native map timer that returns a draw.
This parameter uses Galaxy game seconds (16 loops/second); python-sc2's
`BotAI.time` uses Faster-speed seconds (22.4 loops/second). For example, a limit
of 900 corresponds to approximately 643 Faster-speed seconds of play.
`timeout=90` bounds each API/startup barrier or realtime observation/callback
cycle, not the whole match. Policy exceptions propagate and close the four owned
processes; they do not fabricate match results or invoke `on_end` with invented
outcomes. Normal completion requires matching native results from all clients.
Terminal frames can differ after native `GameOver`, particularly when a realtime
callback returns late.

Each run saves the generated map, player/team/process mapping, initial alliance
checks, terminal results and per-client API journals. A replay is saved when
`save_replay_as` is provided. Existing output directories and replay files are
rejected. Without `output_dir`, a unique directory is created under `reports/`.
`random_seed=None` selects a random uint32 seed and records it for reproduction.

For raw policies, [`NativeFourSession`](../src/mpsc2/native_session.py) remains
available. Its `clients` and `player_ids` follow process order; its fixed-map
alliances must be interpreted using the returned native IDs. It supplies
concurrent `call`, `observe` and `step` barriers without running BotAI callbacks.
It also accepts `realtime=True`; in that mode, `step()` is rejected because the
engine advances automatically.

## Map and current scope

[`maps/MPSC2TeamArena.SC2Map`](../maps/MPSC2TeamArena.SC2Map) is a real four-player
MPQ map with six Marines per player. Players 1+2 and 3+4 have native alliances,
shared teammate vision, and separate command ownership. A team loses when both
of its armies are eliminated. The map draws after 120 game seconds.

The separate economy fixture extends this to mining, construction, production,
expansion and building-based victory. Arbitrary melee-map integration, learned
policies, episode resets and broader reliability work remain for the research
environment. Team totals may still be zero-sum
even though individual players cooperate within each team.

`maps/source/MapScript.galaxy` is the authoritative trigger source. Rebuild with
`scripts/build_map.py`; the inherited visual Triggers component is empty, so an
editor save can regenerate and replace the hand-written script. The fixture is
based on Blizzard's checksum-pinned empty terrain map; provenance is under
`maps/vendor/`. Its display title still comes from that base fixture.

The economy map is built by `scripts/build_melee_map.py` using the shared
`src/mpsc2/RuntimeArena.galaxy` handshake and `src/mpsc2/Melee.galaxy` rules.
`src/mpsc2/arena.py` supplies its base/resource coordinates and pins its checksum.
Both Galaxy templates are included in the Python package.

The native bridge refuses any executable whose SHA256 differs from the tested
Base96883 binary and also verifies its Mach-O UUID and expected runtime state.
Windows, Linux, other SC2 builds, remote hosts and long training campaigns are
not validated. The successful native source is
[`src/mpsc2/native/local_four_bridge.c`](../src/mpsc2/native/local_four_bridge.c).

## Checks and investigation tools

```sh
.venv/bin/python -m pytest -q

# Stock-engine behavior: expected rejection on this installed build.
.venv/bin/python -m mpsc2.probe
.venv/bin/python scripts/probe_raw_protocol.py

# Single-client map diagnostic only.
.venv/bin/python -m mpsc2.smoke --api-players 1 --output reports/map-only
```

The offline suite covers map integrity, observation/alliance checks, fog,
barrier failures, raw framing, partial joins, native build guards, public API
validation, team assignment under permuted native IDs, result ordering,
terminal frame differences, callback failures and cleanup. Realtime tests cover
independent observation cadences, slow callbacks, end-of-game races, timeout
cleanup and the absence of manual stepping.
Economy tests cover reproducible map generation, standard starting resources,
base/worker ownership under permuted player IDs, dynamic building victory,
resource snapshot deduplication and rejection of incomplete production evidence.
Live evidence is essential; unit tests alone do not establish multiplayer support.

The successful bridge's engineering account and compact validation evidence
are retained under `evidence/2026-10-28/`. Superseded experimental scripts,
failed runs, runtime inspection dumps and temporary recordings were removed
during workspace cleanup. Successful test runs and final demo artifacts remain
local in ignored `reports/`.

The public `run_game` / `run_game_async` API was also verified with real BotAI
policies. These runs retain their generated map, replay, results and client logs:

| API run | Team IDs in input order | Returned results |
| --- | --- | --- |
| 2v2 (`reports/run-game-api-2v2-verified/result.json`) | `[7,9,7,9]` | Victory, Defeat, Victory, Defeat |
| 3v1 (`reports/run-game-api-3v1-verified/result.json`) | `[10,10,10,20]` | Victory, Victory, Victory, Defeat |
| Free-for-all (`reports/run-game-api-ffa-verified/result.json`) | `[11,22,33,44]` | Defeat, Defeat, Defeat, Victory |
| Fog and native timer (`reports/run-game-api-fog-draw-verified/result.json`) | `[5,8,5,8]` | Tie, Tie, Tie, Tie |

All four replay result tables match their API results after mapping native IDs
back to input order. The fog run also verified Terran, Zerg and Protoss join
race preservation (the combat fixture still supplies Marines to everyone).
The built wheel was checked for both public entry points and successfully
generated an arena using its packaged Galaxy template.

Realtime validation is retained separately:

| Run | Check |
| --- | --- |
| Realtime 2v2 (`reports/realtime-2v2/result.json`) | Interleaved team IDs, native wins/losses, replay |
| Realtime free-for-all (`reports/realtime-ffa/result.json`) | Different observation intervals; one deliberately delayed bot |
| Realtime 3v1 with fog (`reports/realtime-3v1-fog/result.json`) | Shared teammate vision and native team results |
| Delayed startup and draw (`reports/realtime-startup-draw/result.json`) | Three-second startup delay; native timer starts afterward; game ends during a slow callback |
| Stepped regression (`reports/realtime-stepped-regression/result.json`) | `realtime=False` still steps explicitly and reaches a native draw |

All four realtime runs contain zero `Step` requests in their client journals,
and their saved replay results agree with the API results. The 2v2 run used
Python 3.13; the other runs used Python 3.10. The free-for-all bots completed
57, 44, 29 and 22 callback iterations independently. The offline suite now has
65 passing tests on both Python versions, including the economy-map checks.


## Recorded multiplayer demonstrations

The completed recordings are available at their original paths:

- Four-player free-for-all, 36 seconds (`reports/demo-videos/ffa/ffa.mp4`)
- 3v1, 19 seconds (`reports/demo-videos/3v1/3v1.mp4`)
- 2v2, 35 seconds (`reports/demo-videos/2v2/2v2.mp4`)

Each recording retains its map, replay, poster, result report and client journals.
Video checksums and durations are in videos.json (`reports/demo-videos/videos.json`).
Intermediate capture frames and QA images have been removed.

`scripts/record_demos.py` builds free-for-all (`1|2|3|4`), 3v1 (`1,2,3|4`),
and 2v2 (`1,2|3,4`) variants from `maps/source/DemoArena.galaxy`. Each player
starts with 12 Marines and runs the same nearest-enemy attack policy through
its own SC2 process and API connection. Native alliance classifications are
checked from all four perspectives; every client's terminal result must agree.
The demonstrations use full visibility and no shared unit control.

Install the `video` optional dependencies, then use a fresh output directory:

```sh
.venv/bin/python scripts/record_demos.py --mode all --graphics-api Metal \
  --output reports/new-demo-videos --capture-dir reports/new-demo-videos/capture
```

On this Mac, native Metal game windows render correctly, but the RGB observation
API returns black frames. The recorder therefore waits for a CUA window capture
at each `capture/request.json` path. Save the requested window PNG atomically;
the runner then advances all four clients together and requests the next frame.
Use the SC2 application window only, with no unrelated desktop content. This
handshake requires an attached capture driver; the command alone waits for it.
The `--rgb` path is available for a renderer that actually returns RGB pixels;
blank frames are rejected. Do not use it with the tested Metal Base96883 build.

Videos contain real SC2 window frames with added titles, group membership,
observed unit counts and native results. Capture is four frames per second,
four simulation loops per capture, with three-second opening and four-second
result holds. Playback is approximately 0.71 times SC2's Faster game speed.
Each mode also saves its exact SC2Map, replay, result JSON and four API journals.
These are combat demonstrations, not trained policies or full economy matches.
