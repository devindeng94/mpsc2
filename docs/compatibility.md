# Compatibility and support

Version 0.3.2a2 registers the Windows Base93333 and macOS Base96883 native
backends in explicit [compatibility profiles](version-profiles.md).
Linux supports diagnostics and standard games.
See the [Windows testing guide](windows.md) for the supported testing path.

The compatibility target is the pinned **burnysc2 7.3.0** public API. We reuse
upstream objects rather than copying its unit/economy implementation. Private
underscore-prefixed functions and implementation details are not a compatibility
contract. Upgrading burnysc2 requires rechecking the lifecycle adapters.

| API area | MPSC2 behavior |
| --- | --- |
| `bot_ai`, `bot_ai_internal`, `unit`, `units`, `unit_command`, `action` | Re-export upstream classes and public names |
| `player` | Same `Bot`, `Human`, `Computer`, `BotProcess`, `Observer`, player metadata |
| `data`, `constants`, `ids.*`, `dicts.*` | Same enums and game lookup tables |
| `position`, `pixel_map`, `power_source`, `game_data`, `game_info`, `game_state`, `score` | Re-export upstream data/query structures |
| `client`, `controller`, `protocol`, `portconfig`, `sc2process`, `proxy`, `paths`, `versions` | Re-export upstream low-level APIs; they do not establish multiplayer sessions themselves |
| `cache`, `expiring_dict`, `observer_ai` | Re-export upstream helpers and `ObserverAI` |
| `maps.get` | Adds bundled map names and explicit paths; other names use upstream installed-map lookup |
| `main.run_game` | Upstream signature plus multiplayer keyword options |
| `run_game_async` | Awaitable standard and multiplayer launcher |
| `GameMatch`, `run_multiple_games`, `a_run_multiple_games` | Standard batch delegation; fresh multiplayer sessions for multiplayer |
| `main.run_match`, `main.play_from_websocket` | Standard externally managed matches/ladder connection only |
| `run_replay`, `run_replay_async`, `get_replay_version` | Replay version selection, observer callbacks and optional paced playback |
| Upstream renderer and code generators | Not re-exported; use upstream directly if needed |
| Upstream process-reusing batch internals | Not exposed as multiplayer APIs |

## Game support matrix

| Feature | Standard one/two-player route | Multiplayer scenario route (2–8) |
| --- | --- | --- |
| Engine/platform | Upstream support and installation requirements | Windows Base93333 or macOS Base96883, exact validated executable; two clients use stock hosting, 3–8 use the platform's bridge |
| Maps | Installed upstream maps or explicit standard map path | Packaged `MPSC2TeamArena` and `MPSC2Melee`, resized per match |
| BotAI | Yes | 2–8 distinct instances |
| Human / built-in Computer | Upstream behavior | Unsupported; rejected before launch |
| External BotProcess | Upstream batch runner | Unsupported |
| Realtime / stepped | Upstream behavior | Both; independently observed / synchronized |
| Teams | Upstream standard opponent setup; omit `team_ids` | Any partition of 2–8 bots into at least two teams |
| Replay saving | Upstream single-game option | `save_replay_as`; existing file rejected |
| Custom ports, RGB config | Upstream single-game options | Unsupported; explicit error |
| Version selection | Upstream single-game behavior | `sc2_version` selects a registered native profile; defaults remain pinned |
| Process arguments (`sc2_config`) | Upstream batch runner | Unsupported |
| Fullscreen | Upstream player option | Windowed only |
| Window size / graphics API | Upstream process configuration | `window_size`, `graphics_api` |
| Restart / process reuse | Upstream facilities | Fresh processes per match |
| Player count | One/two standard players | 2–8 independent API clients |
| Upgrade research | Upstream behavior; stock two-client scenario route | Own research/upgrades preserved by the Base96883 observation guard; see [validation](research-validation.md) |

The one-BotAI-versus-Computer route is tested on Blizzard's Bel'Shir Vestige
ladder map in both timing modes, including mining, worker production and a
Depot. The `scripts/validate_player_counts.py` matrix checks 2–8 independent
participants with native results, replay rosters and actual unit commands.
Its melee variant additionally checks mining, worker training and construction.
See [player-count validation](player-count-validation.md) for measured coverage
and limitations. Earlier full economy validation covers four Terran bots in 2v2,
both realtime and stepped. Do not infer other-platform/build or long-training
reliability from these results.

The [alpha audit](alpha-validation.md) adds upstream fixture tests, installed
package checks, mixed-race production and fault handling. Read its failures as
well as successes before selecting a research workload.

## Why the native bridge is required

The stock API rejects more than two independent participants. The backend supplies a
guarded local-lobby initialization and discovery bridge, then runs the requested number of native
participants. It validates the executable SHA256 and runtime state and refuses
unknown binaries. The lobby bridge changes host runtime data. A separate
observation guard changes seven bytes of process-private executable memory in
each 3–8-player client to skip an invalid 1v1-only opponent lookup. Game
installation files are not patched. See [the root cause and guard](known-issues.md).

See [the engineering record](engineering-history.md) for raw-protocol evidence,
native identities, map handshake details and verification of separate control.
Porting to another platform/build is a backend engineering task, not a package
metadata change. Arbitrary map support also requires setup and result rules;
renaming a map does not make it compatible.
