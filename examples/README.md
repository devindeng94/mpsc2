# Examples

Run commands from the repository root after [installation](../docs/installation.md).
Each native multiplayer match requires the supported macOS SC2 build. Use a
fresh `reports/...` directory each time; examples do not overwrite old runs.

| Example | Purpose | Extra dependencies |
| --- | --- | --- |
| [minimal_four_player.py](minimal_four_player.py) | Smallest stepped 2v2 arena launcher | Base package |
| [minimal_realtime.py](minimal_realtime.py) | The same four-client arena in realtime | Base package |
| [multiplayer.py](multiplayer.py) | Configurable 2–8 players and teams, optional replay | Base package |
| [team_game.py](team_game.py) | Four-player team game with per-policy metrics | Base package |
| [full_game.py](full_game.py) | Four Terran bots mining, building, training, expanding and fighting | Base package |
| [versus_computer.py](versus_computer.py) | One Python bot versus a built-in Computer on a separately installed standard map | Base package |
| [replay_analysis.py](replay_analysis.py) | ObserverAI replay callbacks and analysis | Base package |
| [batch_games.py](batch_games.py) | Sequential self-play matches with fresh bot instances | Base package |

## Arena layouts

```sh
python examples/multiplayer.py --players 4 --teams 0 0 1 1 --output reports/arena-2v2
python examples/multiplayer.py --players 4 --teams 0 0 0 1 --output reports/arena-3v1
python examples/multiplayer.py --players 4 --output reports/arena-ffa
python examples/multiplayer.py --players 8 --teams 0 0 0 0 1 1 1 1 --realtime --output reports/arena-4v4
```

The arena supplies Marines and enables full visibility in these examples. It is
useful for control experiments, not for economy testing or policy-strength claims.

## Economy, research and replays

```sh
python examples/full_game.py --teams 7 9 7 9 --output reports/economy-stepped
python examples/full_game.py --realtime --teams 7 9 7 9 --output reports/economy-realtime
python -m mpsc2 replay reports/economy-realtime/game.SC2Replay --speed 2
```

The economy example asserts mining, construction, production, expansion and
combat. It uses normal fog and shared teammate vision. Native fixture time limits
are in Galaxy seconds; see [timing conventions](../docs/migration.md#timing-and-callbacks).

To verify replay tracker events or exercise mixed-race research, install the dev
extra and use the opt-in validation scripts:

```sh
python -m pip install -e '.[dev]'
python scripts/verify_economy_replay.py reports/economy-stepped
python scripts/validate_alpha.py --phase races --output reports/research
python scripts/verify_research_replay.py reports/research --playback
```

These are bounded regression policies. Read the [measured research coverage](../docs/research-validation.md)
for limitations, including the eight-player expansion assertion.

## Standard game against the Computer

Supply an ordinary melee map; the bundled research scenarios accept BotAI players
only. This example uses one API client and two native game players:

```sh
python examples/versus_computer.py /path/to/standard.SC2Map --output reports/vs-computer
```

This policy tests a short economy sequence, rather than a competitive strategy.
