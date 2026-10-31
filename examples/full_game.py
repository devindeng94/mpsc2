"""2..8 independent Terran macro bots: mine, build, train, expand, then fight.

Run from the repository: python examples/full_game.py --output reports/full-game
Add --realtime to use the native clock. No debug commands or resource grants.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from sc2.bot_ai import BotAI
from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.player import Bot
from sc2.position import Point2

from mpsc2 import maps, run_game
from mpsc2.arena import melee_layout


class MacroBot(BotAI):
    def __init__(self, output: Path):
        super().__init__()
        self.output = output
        self.events = []
        self.trained = Counter()
        self.completed = Counter()
        self.snapshots = []
        self.action_errors = Counter()
        self.started_tags = set()
        self.completed_tags = set()

    async def on_start(self):
        self.initial_tags = self.all_own_units.tags
        self.start_loop = self.state.game_loop
        self.initial = {
            "workers": self.workers.amount, "townhalls": self.townhalls.amount,
            "minerals": self.minerals, "vespene": self.vespene,
            "army": self.units.exclude_type(U.SCV).amount,
        }
        self.map_resources = {"mineral_fields": self.mineral_field.amount,
                              "geysers": self.vespene_geyser.amount,
                              "expansion_locations": [list(p) for p in self.expansion_locations_list]}
        self.expansions = [Point2(p) for p in melee_layout(len(self.team_ids))[1]]
        self.expansion = min(self.expansions, key=self.start_location.distance_to)
        self.rally = self.start_location.towards(self.game_info.map_center, 10)
        self.scout_index = 0
        self.next_sample = 0
        self.snapshot()
        print(f"Player {self.player_index}: native ID {self.player_id}, start {self.initial}", flush=True)

    def event(self, kind, unit):
        self.events.append({"loop": self.state.game_loop, "event": kind,
                            "type": unit.type_id.name, "tag": unit.tag, "progress": unit.build_progress})

    async def on_unit_created(self, unit):
        if unit.tag not in self.initial_tags:
            self.trained[unit.type_id.name] += 1
            self.event("trained", unit)

    async def on_building_construction_started(self, unit):
        if unit.tag not in self.initial_tags:
            self.started_tags.add(unit.tag)
            self.event("construction_started", unit)

    async def on_building_construction_complete(self, unit):
        if unit.tag not in self.initial_tags:
            self.completed[unit.type_id.name] += 1
            self.completed_tags.add(unit.tag)
            self.event("construction_completed", unit)

    def snapshot(self):
        score = self.state.score
        data = {
            "loop": self.state.game_loop, "game_seconds": round((self.state.game_loop-self.start_loop)/22.4, 2),
            "minerals": self.minerals, "vespene": self.vespene,
            "collected_minerals": score.collected_minerals, "collected_vespene": score.collected_vespene,
            "spent_minerals": score.spent_minerals, "spent_vespene": score.spent_vespene,
            "workers": self.workers.amount, "army": self.units.of_type({U.MARINE, U.MARAUDER}).amount,
            "structures": dict(Counter(u.type_id.name for u in self.structures.ready)),
            "killed_units": score.killed_value_units, "killed_structures": score.killed_value_structures,
        }
        self.snapshots.append(data)
        return data

    def save(self, result=None):
        data = {
            "player_index": self.player_index, "player_id": self.player_id, "team_id": self.team_id,
            "result": result, "initial": self.initial, "map_resources": self.map_resources, "trained": dict(self.trained),
            "completed": dict(self.completed), "construction_started_and_completed": len(self.started_tags & self.completed_tags),
            "action_errors": dict(self.action_errors), "snapshots": self.snapshots, "events": self.events,
        }
        (self.output / f"player-{self.player_index}.json").write_text(json.dumps(data, indent=2) + "\n")

    async def on_step(self, iteration):
        elapsed = (self.state.game_loop - self.start_loop) / 22.4
        for error in self.state.action_errors:
            self.action_errors[str(error.result)] += 1
        if elapsed >= self.next_sample:
            data = self.snapshot()
            self.save()
            print(f"Player {self.player_index} at {elapsed:.0f}s: mined {data['collected_minerals']:.0f}m/{data['collected_vespene']:.0f}g, "
                  f"workers {data['workers']}, army {data['army']}, built {dict(self.completed)}", flush=True)
            self.next_sample = elapsed + 60

        if iteration % 4 == 0:
            await self.distribute_workers()
            # Fill our refinery even when all mineral workers are busy.
            for refinery in self.gas_buildings.ready:
                needed = refinery.ideal_harvesters - refinery.assigned_harvesters
                candidates = self.workers.filter(lambda w: w.is_collecting and not w.is_carrying_vespene)
                for worker in candidates.sorted_by_distance_to(refinery)[:max(0, needed)]:
                    worker.gather(refinery)

        for base in self.townhalls.ready.idle:
            if self.workers.amount + self.already_pending(U.SCV) < 22 * self.townhalls.ready.amount and self.can_afford(U.SCV):
                base.train(U.SCV)

        if self.supply_left < 7 and self.supply_cap < 200 and not self.already_pending(U.SUPPLYDEPOT) and self.can_afford(U.SUPPLYDEPOT):
            await self.build(U.SUPPLYDEPOT, near=self.start_location.towards(self.game_info.map_center, 8))
        if self.structures(U.SUPPLYDEPOT).ready and self.structures(U.BARRACKS).amount + self.already_pending(U.BARRACKS) < 2 and self.can_afford(U.BARRACKS):
            position = await self.find_placement(U.BARRACKS, near=self.start_location.towards(self.game_info.map_center, 13),
                                                 random_alternative=False, addon_place=True)
            if position:
                await self.build(U.BARRACKS, near=position, max_distance=0)
        if self.structures(U.BARRACKS) and not self.gas_buildings and not self.already_pending(U.REFINERY) and self.can_afford(U.REFINERY):
            await self.build(U.REFINERY, near=self.vespene_geyser.closest_to(self.start_location))

        for barracks in self.structures(U.BARRACKS).ready.idle:
            if (not barracks.has_add_on and not self.structures(U.BARRACKSTECHLAB)
                    and not self.already_pending(U.BARRACKSTECHLAB) and self.can_afford(U.BARRACKSTECHLAB)):
                # Placement queries use the engine; do not issue an impossible addon order.
                # Match python-sc2's addon_place check: a Tech Lab occupies the
                # same 2x2 footprint as a Depot. Its own ability is not a worker
                # placement ability and cannot be queried without its producer.
                if await self.can_place_single(U.SUPPLYDEPOT, barracks.add_on_position):
                    barracks.build(U.BARRACKSTECHLAB)
                    continue
            troop = U.MARAUDER if barracks.has_techlab and self.can_afford(U.MARAUDER) else U.MARINE
            if self.can_afford(troop):
                barracks.train(troop)

        if self.trained['MARAUDER'] and self.townhalls.amount < 2 and not self.already_pending(U.COMMANDCENTER) and self.minerals >= 500:
            await self.expand_now(location=self.expansion, max_distance=2)

        army = self.units.of_type({U.MARINE, U.MARAUDER})
        if elapsed < 240:
            for unit in army.idle:
                unit.attack(self.rally)
        elif army:
            # Use visible enemies and public map topology; no fog-hidden units.
            enemies = self.enemy_units | self.enemy_structures
            if enemies:
                target = enemies.closest_to(army.center).position
            else:
                destinations = self.enemy_start_locations + self.expansions
                target = destinations[self.scout_index % len(destinations)]
                if army.center.distance_to(target) < 5:
                    self.scout_index += 1
                    target = destinations[self.scout_index % len(destinations)]
            for unit in army:
                if unit.is_idle or iteration % 8 == 0:
                    unit.attack(target)

    async def on_end(self, result):
        self.snapshot()
        self.save(result.name)
        print(f"Player {self.player_index}: {result.name}, trained {dict(self.trained)}, built {dict(self.completed)}", flush=True)


def validate_economy(output: Path) -> dict:
    players = [json.loads(path.read_text()) for path in sorted(output.glob('player-*.json'))]
    if not 2 <= len(players) <= 8 or sorted(p['player_index'] for p in players) != list(range(len(players))):
        raise ValueError('Expected one player report per input slot for 2..8 players')
    result_path = output / 'result.json'
    if result_path.exists() and len(json.loads(result_path.read_text())['players']) != len(players):
        raise ValueError('Player reports do not match the native session count')
    for player in players:
        last = player['snapshots'][-1]
        checks = {
            "standard_start": player['initial'] == {'workers': 12, 'townhalls': 1, 'minerals': 50, 'vespene': 0, 'army': 0},
            "mined_minerals_and_gas": last['collected_minerals'] > 1000 and last['collected_vespene'] > 100,
            "spent_minerals_and_gas": last['spent_minerals'] > 1000 and last['spent_vespene'] > 50,
            "completed_production_chain": all(player['completed'].get(t, 0) > 0 for t in ['SUPPLYDEPOT','BARRACKS','REFINERY','BARRACKSTECHLAB']),
            "trained_workers_and_army": all(player['trained'].get(t, 0) > 0 for t in ['SCV','MARINE','MARAUDER']),
            "observed_construction_progress": player['construction_started_and_completed'] >= 4,
            "expanded": player['completed'].get('COMMANDCENTER', 0) > 0,
            "fought": last['killed_units'] + last['killed_structures'] > 0,
        }
        player['checks'] = checks
    summary = {'passed': all(all(p['checks'].values()) for p in players), 'players': [
        {k: p[k] for k in ('player_index','player_id','team_id','result','trained','completed','checks')}
        | {'last_observation': p['snapshots'][-1], 'action_errors': p['action_errors']} for p in players
    ]}
    (output / 'economy-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--teams', nargs="+", type=int, default=[0, 0, 1, 1])
    parser.add_argument('--realtime', action='store_true')
    parser.add_argument('--game-time-limit', type=float, default=900)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    results = run_game(
        maps.get('MPSC2Melee'),
        [Bot(Race.Terran, MacroBot(output), name=f'Macro-{i+1}') for i in range(len(args.teams))],
        realtime=args.realtime, team_ids=args.teams, game_time_limit=args.game_time_limit,
        step_size=16, random_seed=7, output_dir=output, save_replay_as=output / 'game.SC2Replay',
    )
    summary = validate_economy(output)
    print('Native results:', [r.name for r in results], 'Economy checks:', summary['passed'], flush=True)
    if not summary['passed']:
        raise SystemExit('Economy checks failed; inspect economy-summary.json')


if __name__ == '__main__':
    main()
