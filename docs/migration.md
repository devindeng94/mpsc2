# Migrating from python-sc2

MPSC2 0.3 targets **burnysc2 7.3.0**, which installs the `sc2` namespace. The
older distribution named `sc2` is not a supported dependency. Install MPSC2 in
a dedicated environment; do not install both python-sc2 distributions together.

## Keep existing bot code

```python
from sc2.bot_ai import BotAI
from sc2.data import Race
from sc2.player import Bot
from sc2.ids.unit_typeid import UnitTypeId
from mpsc2 import maps
from mpsc2.main import run_game  # launcher changes

# MyBot is your existing BotAI subclass.
results = run_game(
    maps.get("MPSC2Melee"),
    [Bot(Race.Terran, MyBot()) for _ in range(4)],
    team_ids=[0, 0, 1, 1],
    realtime=False,
)
```

For a standard game, keep its installed map and original one/two-player list.
Omit `team_ids`; MPSC2 delegates to upstream. Standard `run_game` returns the
upstream scalar result for one API participant or a list for two API participants.
Multiplayer scenarios return one result per input bot, in input player order.
Two bots on a bundled scenario automatically use the multiplayer lifecycle;
the stock two-client engine path is sufficient, so no native bridge is loaded.

Alternatively replace the import prefix `sc2` with `mpsc2` in your bot modules.
The re-exports preserve object identity: `mpsc2.bot_ai.BotAI is sc2.bot_ai.BotAI`.
Unit commands, `Units` filters, enums, points, costs, resource helpers, construction,
training, abilities, queries, events and upgrades use the same implementations.
See the [coverage table](compatibility.md) for the public modules.

## Update assumptions about opponents

- Do not compute an enemy ID as `3 - self.player_id`. Use `self.enemy_player_ids`.
- Input index and native ID differ. `self.player_index` is zero-based input order;
  `self.player_id` is the native ID from `JoinGame`. Guests can join in any order.
- `self.enemy_race` is singular and remains `None` for matches with three or more players.
  Use `self.enemy_races`, a native-ID-to-`Race` mapping. Random selections may
  remain `Race.Random` until your policy identifies visible units.
- `self.units`, workers and structures still contain only your own units.
  `self.enemy_units` and `self.enemy_structures` exclude teammates.
- Use `allied_units(self)` and `allied_units(self, structures=True)` for visible
  teammate units/buildings. These helpers do not expose hidden units or grant
  shared control. Teammates share vision, not a resource bank.
- On `MPSC2Melee`, `self.enemy_start_locations` contains all enemy base starts.
  `self.player_start_locations` maps every native ID to a public map position.
  Start positions are known map topology; observations still obey fog.

```python
from mpsc2 import allied_units

async def on_start(self):
    print(self.team)  # immutable TeamInfo
    print(self.team_id, self.ally_player_ids, self.enemy_player_ids)
    print(allied_units(self).amount)
```

Use a new bot object per player and preferably per episode. MPSC2 initializes
upstream state, but cannot reset arbitrary fields in your subclass.

## Timing and callbacks

The normal lifecycle is `on_before_start`, `on_start`, event callbacks,
`on_step`, action flush, and `on_end`. Setup verifies ownership and alliances
before calling your bot. `on_end` receives the native result only on normal
completion; an exception propagates and cleans up the owned sessions.

With `realtime=False`, every client advances together. All bots must use the
same integer `self.client.game_step` (1..224), initially `step_size=8`.
With `realtime=True`, each bot requests future observations independently;
the runner sends no manual step requests. Different observation intervals are
allowed. Slow bots can skip frames. All policies share one Python event loop,
so blocking computation in a callback blocks the other policies; offload it.

Do not call `client.step`, `leave`, `quit`, `restart` or `_advance_steps` from a
multiplayer bot. The runner owns the shared simulation and process lifecycle.

Multiplayer `game_time_limit` retains the original MPSC2 map convention:
**Galaxy seconds (16 loops/second)**. `BotAI.time` uses **22.4 loops/second**.
A limit of 900 is about 643 Faster-speed seconds. Standard games retain
python-sc2's timing convention. In realtime multiplayer, initialization does
not consume the map timer; absolute `BotAI.time` includes initialization.

## Async and batch self-play

In notebooks or an active event loop:

```python
from mpsc2 import run_game_async
results = await run_game_async("MPSC2Melee", players, team_ids=[7, 9, 7, 9])
```

For multiple episodes:

```python
from mpsc2 import GameMatch, run_multiple_games

matches = [GameMatch(
    "MPSC2Melee",
    [Bot(Race.Terran, MyBot()) for _ in range(4)],
    team_ids=[0, 0, 1, 1], random_seed=seed,
) for seed in range(3)]
results = run_multiple_games(matches)
print([results[0][player] for player in matches[0].players])
```

Async alternatives are `run_multiple_games_async` and `a_run_multiple_games`.
Matches run sequentially and failures stop the batch. Multiplayer processes
are recreated each episode; existing output directories cannot be reused.
Default directories are unique. Upstream `GameMatch` objects are accepted too,
but use MPSC2's class for `team_ids` and replay/output options.

This is a game orchestration package, not a Gym/PettingZoo environment or a
learning algorithm. Rewards, trajectories, policy training and evaluation remain
your research code. Learned policies can implement the same BotAI callbacks.
