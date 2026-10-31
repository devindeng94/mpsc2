# Player-count validation — 0.3.0

The launcher now accepts **2–8 independent BotAI participants**, including odd
counts. The number of clients comes from `len(players)`; `team_ids` has the same
length. Equal labels cooperate, different labels compete, and omitted labels
produce free-for-all. One BotAI versus SC2's built-in Computer uses the standard
python-sc2 route on an ordinary melee map.

## Live coverage on 2026-10-30

Tests ran on macOS with SC2 5.0.15 / Base96883 and burnysc2 7.3.0. Every count
was actually launched. These are engine integration results, not mocked tests.

| Game configuration | Stepped | Realtime | Independent API clients |
| --- | --- | --- | --- |
| One BotAI vs built-in Computer | Passed economy check | Passed economy check | 1; two game players |
| 2 BotAI players | Passed economy check | Passed arena check | 2 |
| 3 BotAI players | Passed arena check | Passed arena check | 3 |
| 4 BotAI players | Passed economy check | Passed arena check | 4 |
| 5 BotAI players | Passed arena check | Passed arena check | 5 |
| 6 BotAI players | Passed economy check | Passed arena check | 6 |
| 7 BotAI players | Passed economy check | Passed arena check | 7 |
| 8 BotAI players | Passed arena and corrected economy checks | Passed arena check | 8 |

The native matrix uses interleaved team labels `[0, 1, 0, 1, ...]`, exercising
input-slot/native-ID mapping and unequal teams for odd counts. Each passed run
checks distinct process IDs, API ports and native player IDs; the complete
observed roster; allied-unit classification; actual movement from each policy;
nonzero action requests; `on_end` callbacks; complete native result tables; and
the player roster in the saved replay. Realtime journals contain **zero
RequestStep calls**. Neither mode uses debug requests.

Arena probes run for five Galaxy seconds after setup and deliberately end in a
native draw. Economy probes run for 60 Galaxy seconds (about 43 Faster-speed
seconds), and additionally require **each bot** to mine minerals, train workers
above its starting 12, and finish a building beyond its starting townhall.
They test launch, control and basic economy; they are not full combat campaigns.

The standard opponent tests use Blizzard's
[Bel'Shir Vestige ladder map](https://github.com/Blizzard/s2client-api/tree/master/maps/Ladder).
In each timing mode, the Python policy collected 710 minerals, reached 16
workers and completed a Supply Depot. The built-in Computer moved units and
reached 16 workers. These standard games stop at the upstream 60-second limit;
their reported `Tie` is the upstream timeout outcome, not a native victory.

The machine-readable record is
[`player-count-validation.json`](../evidence/2026-10-30/player-count-validation.json).
It includes report locations, replay hashes, native IDs, request totals and
failed attempts. Large replays and per-client logs remain in local `reports/`.

## Findings and corrections

- The old four-player constants existed in the map slot records, Galaxy arrays,
  spawn layouts, Python session, discovery fan-out and native readiness checks.
  All now follow the requested count. Two clients use stock hosting without
  loading the bridge; three through eight use the guarded bridge.
- An initial eight-client arena attempt timed out at the 90-second join barrier.
  Readiness-progress diagnostics were added. Subsequent eight-client arena
  runs passed in both timing modes. The initial timeout's root cause remains
  unconfirmed; these runs do not establish a startup reliability rate.
- The first expanded economy layout used a top row outside the playable area.
  Although all eight clients joined and the game ended, one policy failed the
  movement/economy checks. Replay inspection showed SC2 relocating a starting
  townhall. The terrain canvas is 128×128, but its playable bounds are
  `(10, 8)` through `(118, 108)`. The grid was moved inward, resource footprints
  were checked, and startup now rejects displaced townhalls before bot callbacks.
  The earlier six/seven-player economy runs used the initial geometry and are
  retained as historical evidence, not final-layout validations.

The corrected eight-player economy run passed using the installed 0.3.0 wheel
on Python 3.10, launched from outside the checkout. All eight starting bases
passed the position guard. Every bot moved, collected **395–455 minerals**,
grew from **12 to 15 workers**, and completed **one Supply Depot**. All eight
clients returned native draws, and the saved replay contains all eight players.
This used `step_size=16`; the other stepped probes used eight loops per step.

The offline suite has **149 passing tests on Python 3.10 and 3.13**, with SC2
discovery disabled. Coverage includes every supported count, both generated
map types, team validation, default free-for-all, routing, map boundaries and
the displaced-townhall regression. The original four-player source maps and
their checksums are preserved.

## Reproduce

Install the project, run `python -m mpsc2 doctor`, and choose fresh output paths:

```sh
python scripts/validate_player_counts.py --output reports/counts-new
python scripts/validate_player_counts.py --realtime --output reports/counts-rt-new
python scripts/validate_player_counts.py --scenario melee --step-size 16 --output reports/counts-economy-new
python examples/versus_computer.py path/to/standard.SC2Map --output reports/computer-new
python examples/versus_computer.py path/to/standard.SC2Map --realtime --output reports/computer-rt-new
```

For an eight-player 4v4 game with ordinary `BotAI` policies:

```python
from mpsc2 import run_game
from mpsc2.bot_ai import BotAI
from mpsc2.data import Race
from mpsc2.player import Bot

class AttackBot(BotAI):
    async def on_step(self, iteration):
        if self.enemy_units:
            for unit in self.units:
                unit.attack(self.enemy_units.closest_to(unit))

if __name__ == "__main__":
    results = run_game(
        "MPSC2TeamArena",
        [Bot(Race.Terran, AttackBot()) for _ in range(8)],
        team_ids=[0, 0, 0, 0, 1, 1, 1, 1],
        realtime=True,
        disable_fog=True,
        save_replay_as="eight-players.SC2Replay",
    )
    print(results)  # Input order, independent of native join order.
```

Use `range(N)` for free-for-all teams, or supply any integer partition containing
at least two different labels. Use `MPSC2Melee` and a macro policy for economy
games; the arena starts with Marines. The variable-count CLI example is
[`examples/multiplayer.py`](../examples/multiplayer.py).

## Limits of this result

The bundled scenario backend remains pinned to the validated macOS executable.
Windows/Linux, other SC2 builds, arbitrary maps, more than eight players,
networked hosts and sustained training reliability are not established here.
Human/Computer opponents are supported through the standard map route, not as
participants in the bundled multiplayer scenarios. Human gameplay was not
automated in this matrix.

Earlier full Terran economy/combat campaigns cover four players in 2v2, in both
timing modes. The larger-count checks do not establish complete build orders,
expansion, gas production and combat for every race/count/team partition.
See the [support matrix](compatibility.md) and [engineering history](engineering-history.md).
