"""One Python BotAI versus SC2's built-in Computer on a standard melee map.

python examples/versus_computer.py path/to/standard.SC2Map --output reports/computer-new
The built-in opponent shares the one SC2 process; it is not a second API client.
"""
import argparse
import json
from pathlib import Path

from mpsc2 import run_game
from mpsc2.bot_ai import BotAI
from mpsc2.data import Race, Difficulty
from mpsc2.ids.unit_typeid import UnitTypeId as U
from mpsc2.player import Bot, Computer


class EconomyBot(BotAI):
    async def on_start(self):
        self.steps = 0
        self.max_workers = 0
        self.max_structures = 0
        self.collected = 0
        self.enemy_positions = {}
        self.enemy_moved = False
        self.enemy_issued_orders = False
        self.max_enemy_workers = 0

    async def on_step(self, iteration):
        self.steps += 1
        self.collected = max(self.collected, self.state.score.collected_minerals)
        self.max_workers = max(self.max_workers, self.workers.amount)
        self.max_structures = max(self.max_structures, self.structures.amount)
        self.max_enemy_workers = max(self.max_enemy_workers, self.enemy_units.of_type({U.SCV, U.PROBE, U.DRONE}).amount)
        for enemy in self.enemy_units:
            self.enemy_issued_orders |= bool(enemy.orders)
            previous = self.enemy_positions.setdefault(enemy.tag, enemy.position)
            self.enemy_moved |= enemy.distance_to(previous) > 0.5
        if iteration % 4 == 0:
            await self.distribute_workers()
        for base in self.townhalls.ready.idle:
            if self.workers.amount < 18 and self.can_afford(U.SCV):
                base.train(U.SCV)
        if self.supply_left < 5 and not self.already_pending(U.SUPPLYDEPOT) and self.can_afford(U.SUPPLYDEPOT):
            await self.build(U.SUPPLYDEPOT, near=self.start_location.towards(self.game_info.map_center, 8))

    async def on_end(self, result):
        self.result = result.name


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('map')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--realtime', action='store_true')
    parser.add_argument('--seconds', type=float, default=60)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    bot = EconomyBot()
    result = run_game(
        args.map, [Bot(Race.Terran, bot), Computer(Race.Terran, Difficulty.Easy)],
        realtime=args.realtime, disable_fog=True, random_seed=37,
        game_time_limit=args.seconds, save_replay_as=args.output/'game.SC2Replay',
    )
    evidence = {name: getattr(bot, name) for name in [
        'steps', 'collected', 'max_workers', 'max_structures', 'enemy_moved',
        'enemy_issued_orders', 'max_enemy_workers', 'result',
    ]}
    evidence.update(realtime=args.realtime, api_clients=1, total_players=2,
                    opponent='SC2 Computer, Terran, Easy', bounded_seconds=args.seconds)
    (args.output/'validation.json').write_text(json.dumps(evidence, indent=2)+'\n')
    assert bot.steps > 0 and bot.collected > 0 and bot.max_workers > 12 and bot.max_structures > 1
    assert bot.enemy_moved and bot.max_enemy_workers > 12
    assert bot.result == result.name
    print(json.dumps(evidence, indent=2), flush=True)
