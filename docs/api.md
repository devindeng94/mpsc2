# Public API

Import these entry points from `mpsc2` or `mpsc2.main` unless noted otherwise.
All game objects use the pinned upstream python-sc2 implementations. See
[compatibility](compatibility.md) for the scope of each route.

## Game launch

```python
def run_game(
    map_settings, players, realtime=False, portconfig=None,
    save_replay_as=None, game_time_limit=None, rgb_render_config=None,
    random_seed=None, sc2_version=None, disable_fog=False,
    *, team_ids=None, output_dir=None, step_size=8, timeout=90,
    graphics_api=None, window_size=None,
):
    ...
```

`run_game_async` accepts the same arguments. Sync entry points raise a clear
error inside an existing event loop; use their async counterparts there.

| Parameter | Meaning |
| --- | --- |
| `map_settings` | Upstream `Map`, bundled name, installed map name, or SC2Map path |
| `players` | One/two standard players or 2–8 `Bot` objects with distinct `BotAI` instances |
| `realtime` | Engine clock if true; synchronized stepping otherwise |
| `team_ids` | One integer label per bot in input order; omitted means free-for-all. Omit for standard games |
| `save_replay_as` | Optional replay destination; multiplayer refuses an existing file |
| `game_time_limit` | Standard: upstream default/convention. Multiplayer: Galaxy seconds, defaults to 120 arena / 900 melee; range 1..86400 |
| `random_seed` | Unsigned 32-bit integer or None; native route chooses and records a seed for None |
| `disable_fog` | Reveal opponents for demonstrations/testing; false retains fog and shared teammate vision |
| `output_dir` | Multiplayer evidence directory; must not exist. Default: unique `reports/game-*` |
| `step_size` | Multiplayer initial `client.game_step`, integer 1..224 |
| `timeout` | Positive finite seconds per multiplayer startup/API barrier or realtime observation/callback cycle; not a total match duration |
| `graphics_api` | Optional multiplayer engine graphics API string, e.g. `Metal` on macOS |
| `window_size` | Optional positive `(width, height)` multiplayer window dimensions |
| `portconfig`, `rgb_render_config`, `sc2_version` | Standard single-game options only |

Multiplayer returns `list[Result]` in the **input player order**, independent
of native join order. Standard calls preserve upstream scalar/list results.
Unsupported configuration fails explicitly. Runtime errors propagate and
cleanup releases owned processes; errors do not become wins, losses or draws.
The map timer can produce a real native draw.

As in python-sc2, a policy can set `self.raw_affects_selection = True` before
launch. Native sessions pass this preference to that player's client before
joining; the default remains the upstream default. The value must be bool or None.

Each native run reserves a fresh output directory and writes `game.SC2Map`,
`result.json` and `session/` (build records, engine logs and per-client API
journals). Replays are saved only when requested. `result.json` records failures
as well as completed runs; API responses are preserved for investigation.

## Bot team metadata

The following are available before `on_before_start`:

| Attribute | Meaning |
| --- | --- |
| `player_index` | Zero-based input position |
| `player_id` | Native SC2 ID |
| `team_id` | Input team label |
| `team_ids` | Native player ID → input team label |
| `ally_player_ids`, `enemy_player_ids` | Tuples of native IDs |
| `enemy_races` | Native enemy ID → declared `Race` |
| `team` | Immutable `TeamInfo`, with an immutable copy of the ID mapping |
| `player_start_locations` | Melee only: native player ID → public base `Point2` |

`from mpsc2 import TeamInfo, allied_units` provides the metadata type and the
visible-allies helper. `allied_units(ai, structures=False)` returns an upstream
`Units` collection; `structures=True` selects buildings. Ownership and command
permissions do not change. Singular upstream `enemy_race` is not meaningful for
multiple opponents.

## Maps

`from mpsc2 import maps`:

- `maps.available()` returns bundled names, without requiring SC2.
- `maps.get(name_or_path)` returns an upstream `Map` object. Bundled names and
  existing paths work independently of the current working directory and SC2
  installation. Other names use upstream installed-map lookup.
- `maps.Map` is the original upstream class. Its constructor still follows
  upstream path discovery; prefer `maps.get` for portable packaged paths.

The source map is never modified. Each multiplayer run creates its own copy
with the requested slot count, team handshake and time limit. Only checksum-pinned
source maps are accepted. Arena slots contain six Marines each. Melee slots have
one base, twelve workers, and one expansion site per player. Five to eight melee
players use an expanded grid; the original four-player geometry is unchanged.
Bundled multiplayer maps accept 2–8 BotAI players. Two bots automatically use
the multiplayer lifecycle with stock two-client hosting (no bridge). Human and
Computer opponents use ordinary standard maps through the upstream route.

## Batch games

`GameMatch` preserves upstream's first fields and adds multiplayer options:

```python
GameMatch(map_sc2, players, realtime=False, random_seed=None,
          disable_fog=None, sc2_config=None, game_time_limit=None,
          team_ids=None, save_replay_as=None, output_dir=None,
          step_size=8, timeout=90, graphics_api=None, window_size=None)
```

`run_multiple_games(matches)` returns `list[dict[player_object, Result]]` in
match order. `run_multiple_games_async` / `a_run_multiple_games` are awaitable.
Matches run sequentially. Multiplayer sessions use fresh processes. Reuse of a
single `Bot` object within one match is rejected because result keys would collide.
Use fresh bot instances across episodes to reset your own policy state.

Standard batch games delegate to upstream, including `BotProcess` and
`sc2_config`. Multiplayer-only options are rejected on this path; use single-game
`run_game` to save standard replays. `main.run_match` accepts already-created
controllers for standard matches only. `main.play_from_websocket` forwards the
upstream standard ladder/externally hosted-game API; neither sets up multiplayer
teams or the native bridge.

## Replays

```python
run_replay(ai, replay_path, realtime=False, observed_id=0,
           speed=1.0, step_size=4, timeout=90, max_game_loop=None,
           graphics_api=None, window_size=(1280, 800))
```

`run_replay_async` is the awaitable equivalent. `ai` is an upstream/MPSC2
`ObserverAI`, or `None` for viewing. `observed_id` is a native player ID; zero
requests the all-player view. A matching replay build and game data must exist
in the installation. `get_replay_version(path)` returns `(BaseBuild, DataVersion)`.

Replay `realtime=True` uses wall-clock-paced explicit steps at 22.4 loops/second
times `speed`. This differs from game `realtime=True`, which uses the native
engine clock. `realtime=False` runs analysis as fast as possible. `step_size`
controls sampling, so large steps can miss short-lived units/events.
`max_game_loop` bounds a preview at an absolute replay frame.

Return value: native player-ID-to-`Result` dictionary, or `{}` for a preview
that ends before native results. Observer callbacks are `on_start`, events,
`on_step` and `on_end`. `on_end` receives the selected player's result, or `None`
for player-zero viewing / bounded previews. The adapter fixes upstream's
`Race.NoRace` structure classification and propagates the chosen observed ID.
Cancelling or completing the replay closes its owned SC2 process.
On macOS Base96883, selected-player views with native IDs >=4 require the same
checksum-pinned observation guard used in multiplayer games (and `clang` to
build it). This fixes the engine's `3-player_id` upgrade lookup; other replay
builds and views keep the ordinary path.
The replay adapter supplies missing upstream ObserverAI damage, type-change and
vision callbacks as temporary no-ops on that instance. User overrides run
normally, and the upstream class is never modified.

## Diagnostics and command line

`from mpsc2 import get_capabilities` returns a JSON-serializable support report
with static local checks. `ready` does not guarantee graphics/game data/network
runtime health; an actual game is the integration check.

```sh
mpsc2 --version
mpsc2 maps
mpsc2 doctor
mpsc2 replay path.SC2Replay --speed 2
mpsc2 replay path.SC2Replay --fast --step-size 224
```

The same commands work as `python -m mpsc2`. Existing `mpsc2-smoke` and
`mpsc2-probe` research diagnostics remain available.

For low-level policies, `mpsc2.native_session.NativeMultiplayerSession(...,
players=N)` exposes 2–8 independent clients and their input-order native IDs.
Use a correctly prepared runtime map and the documented handshake; the session
alone does not run BotAI or configure policy teams. `NativeFourSession` remains
as a backward-compatible four-player wrapper. Two-client sessions load no bridge.
