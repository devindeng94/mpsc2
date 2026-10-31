"""Opt-in release checks with real SC2 processes, actions, failures and replays.

Use a fresh --output directory. Phases can be run separately to resume an audit.
python scripts/validate_alpha.py --phase races --output reports/alpha-races-new
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import json
from pathlib import Path
import psutil

from mpsc2 import GameMatch, allied_units, run_game_async, run_multiple_games_async, run_replay_async
from mpsc2.bot_ai import BotAI
from mpsc2.data import Race, Result
from mpsc2.ids.unit_typeid import UnitTypeId as U
from mpsc2.ids.upgrade_id import UpgradeId as G
from mpsc2.observer_ai import ObserverAI
from mpsc2.player import Bot, Computer


def write(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')


def assert_processes_closed(report):
    for player in report['players']:
        # os.kill(pid, 0) is a POSIX probe but can terminate a Windows process.
        try:
            process = psutil.Process(player['pid'])
            started = player.get('process_create_time')
            if started is not None and process.create_time() != started:
                continue  # Windows can recycle a PID immediately after cleanup.
            if started is None and process.name().lower() not in {'sc2', 'sc2_x64.exe', 'sc2_x64'}:
                continue  # compatibility with historical reports lacking identity
        except psutil.NoSuchProcess:
            continue
        raise AssertionError(f"Owned SC2 process remains alive: {player['pid']}")


class RaceBot(BotAI):
    def __init__(self, raw_selection=False, research=True):
        super().__init__()
        self.raw_affects_selection = raw_selection
        self.research_enabled = research
        self.events = Counter()
        self.max_workers = 0
        self.collected = [0, 0]
        self.query_checks = {}
        self.history = []
        self.steps = 0

    async def on_before_start(self):
        self.history.append('before_start')
        assert self.team.player_id == self.player_id

    async def on_start(self):
        self.history.append('start')
        self.initial_tags = self.all_own_units.tags
        self.plan = {
            Race.Terran: (U.SCV, U.SUPPLYDEPOT, U.BARRACKS, U.REFINERY, U.MARINE, U.ENGINEERINGBAY, G.TERRANINFANTRYWEAPONSLEVEL1),
            Race.Protoss: (U.PROBE, U.PYLON, U.GATEWAY, U.ASSIMILATOR, U.ZEALOT, U.FORGE, G.PROTOSSGROUNDWEAPONSLEVEL1),
            Race.Zerg: (U.DRONE, U.OVERLORD, U.SPAWNINGPOOL, U.EXTRACTOR, U.ZERGLING, U.SPAWNINGPOOL, G.ZERGLINGMOVEMENTSPEED),
        }[self.race]
        assert self.workers.amount == 12 and self.townhalls.amount == 1
        assert self.minerals == 50 and self.vespene == 0
        assert allied_units(self).amount >= 12 * len(self.ally_player_ids)
        assert len(self.enemy_start_locations) == len(self.enemy_player_ids)
        assert self.client.raw_affects_selection is self.raw_affects_selection
        abilities = await self.get_available_abilities([self.townhalls.first, self.workers.first])
        assert len(abilities) == 2 and all(abilities)
        distance = await self.client.query_pathing(self.workers.first, self.start_location.towards(self.game_info.map_center, 12))
        assert distance is not None and distance > 0
        expansion = await self.get_next_expansion()
        assert expansion is not None
        worker, _, production, _, army, _, _ = self.plan
        assert self.calculate_cost(worker).minerals == 50
        assert self.calculate_supply_cost(worker) == 1
        assert self.calculate_unit_value(army).minerals > 0
        assert self.units.of_type({worker}).amount == 12
        assert self.workers.closest_to(self.start_location).tag in self.workers.tags
        self.query_checks = {'abilities': True, 'pathing_distance': distance,
                             'expansion': list(expansion), 'cost_and_supply': True, 'unit_collections': True}
        self.production = production

    async def ensure_building(self, kind, near):
        if not self.structures(kind) and not self.already_pending(kind) and self.can_afford(kind):
            await self.build(kind, near=near)

    async def on_step(self, iteration):
        self.steps += 1
        self.max_workers = max(self.max_workers, self.workers.amount)
        self.collected = [max(self.collected[0], self.state.score.collected_minerals),
                          max(self.collected[1], self.state.score.collected_vespene)]
        worker, supply, production, gas, army, research_building, upgrade = self.plan
        if iteration % 4 == 0:
            await self.distribute_workers()
            for refinery in self.gas_buildings.ready:
                needed = max(0, refinery.ideal_harvesters - refinery.assigned_harvesters)
                candidates = self.workers.filter(lambda w: w.is_collecting and not w.is_carrying_vespene)
                for unit in candidates.sorted_by_distance_to(refinery)[:needed]:
                    unit.gather(refinery)
        if self.supply_left < 6 and not self.already_pending(supply) and self.can_afford(supply):
            if self.race == Race.Zerg:
                self.train(supply)
            else:
                await self.build(supply, near=self.start_location.towards(self.game_info.map_center, 7))
        if self.workers.amount + self.already_pending(worker) < 20:
            self.train(worker)
        near = self.start_location.towards(self.game_info.map_center, 6)
        if self.race == Race.Protoss:
            if not self.structures(U.PYLON).ready:
                return
            near = self.structures(U.PYLON).ready.first.position
        if self.race != Race.Terran or self.structures(U.SUPPLYDEPOT).ready:
            await self.ensure_building(production, near)
        if self.structures(production):
            if not self.gas_buildings and not self.already_pending(gas) and self.can_afford(gas):
                await self.build(gas, near=self.vespene_geyser.closest_to(self.start_location))
            await self.ensure_building(research_building, near)
        if self.structures(production).ready and self.units(army).amount + self.already_pending(army) < 6:
            self.train(army)
        if self.research_enabled and not self.already_pending_upgrade(upgrade):
            self.research(upgrade)
        expansion_ready = upgrade in self.state.upgrades if self.research_enabled else self.collected[1] > 100
        if expansion_ready and self.townhalls.amount < 2 and self.minerals >= 450:
            base = {Race.Terran: U.COMMANDCENTER, Race.Protoss: U.NEXUS, Race.Zerg: U.HATCHERY}[self.race]
            if not self.already_pending(base):
                await self.expand_now()
        if iteration % 80 == 0:
            print(f'Race {self.player_index} {self.race.name}: t={self.time:.0f}, workers={self.workers.amount}, '
                  f'army={self.units(army).amount}, upgrades={[u.name for u in self.state.upgrades]}', flush=True)

    async def on_unit_created(self, unit):
        if unit.tag not in self.initial_tags:
            self.events['created_' + unit.type_id.name] += 1

    async def on_building_construction_started(self, unit):
        if unit.tag not in self.initial_tags:
            self.events['construction_started'] += 1

    async def on_building_construction_complete(self, unit):
        if unit.tag not in self.initial_tags:
            self.events['complete_' + unit.type_id.name] += 1

    async def on_upgrade_complete(self, upgrade):
        self.events['upgrade_' + upgrade.name] += 1

    async def on_unit_type_changed(self, unit, previous_type):
        self.events['type_changed'] += 1

    async def on_end(self, result):
        self.history.append('end')
        self.result = result.name

    def summary(self):
        return {'race': self.race.name if self.race is not None else None, 'history': self.history, 'steps': self.steps,
                'events': dict(self.events), 'queries': self.query_checks,
                'collected': self.collected, 'max_workers': self.max_workers, 'result': getattr(self,'result',None),
                'raw_affects_selection':self.raw_affects_selection, 'research_enabled':self.research_enabled}


class CombatBot(BotAI):
    def __init__(self):
        super().__init__()
        self.events = Counter()
        self.steps = 0

    async def on_start(self):
        self.hidden_at_start = not self.enemy_units

    async def on_step(self, iteration):
        self.steps += 1
        for unit in self.units:
            if self.enemy_units:
                unit.attack(self.enemy_units.closest_to(unit))
            elif unit.is_idle:
                unit.attack(self.game_info.map_center)

    async def on_unit_destroyed(self, tag):
        self.events['destroyed'] += 1

    async def on_unit_took_damage(self, unit, amount):
        assert amount > 0
        self.events['damage'] += 1

    async def on_enemy_unit_entered_vision(self, unit):
        self.events['entered_vision'] += 1

    async def on_enemy_unit_left_vision(self, tag):
        self.events['left_vision'] += 1

    async def on_end(self, result):
        self.result = result.name


class AuditObserver(ObserverAI):
    async def on_start(self):
        self.steps = 0
        self.max_structures = 0
        self.ended = False

    async def on_step(self, iteration):
        self.steps += 1
        self.max_structures = max(self.max_structures, self.structures.amount)

    async def on_end(self, result):
        self.ended = True
        self.result = result.name if result is not None else None


async def race_check(output, raw_selection=False, races=(Race.Terran, Race.Protoss, Race.Zerg, Race.Random), research=True, realtime=False, step_size=112, require_expansion=True):
    bots = [RaceBot(raw_selection,research) for _ in races]
    try:
        results = await run_game_async('MPSC2Melee',
            [Bot(r, b) for r, b in zip(races, bots)],
            realtime=realtime,
            team_ids=[7 if i % 2 == 0 else 9 for i in range(len(bots))], game_time_limit=500, step_size=step_size, random_seed=71,
            output_dir=output/'game', save_replay_as=output/'game.SC2Replay')
    finally:
        write(output/'bots.json', [b.summary() for b in bots])
    metrics = [b.summary() for b in bots]
    write(output/'bots.json', metrics)
    for bot in bots:
        worker, _, production, gas, army, _, upgrade = bot.plan
        base = {Race.Terran: U.COMMANDCENTER, Race.Protoss: U.NEXUS, Race.Zerg: U.HATCHERY}[bot.race]
        assert bot.history == ['before_start', 'start', 'end'] and bot.steps > 0
        assert bot.max_workers > 12 and bot.collected[0] > 1000 and bot.collected[1] > 100, bot.summary()
        required = ['created_'+worker.name, 'created_'+army.name, 'complete_'+production.name,
                    'complete_'+gas.name, 'construction_started']
        if require_expansion:
            required.append('complete_'+base.name)
        if research:
            required.append('upgrade_'+upgrade.name)
        for key in required:
            assert bot.events[key] > 0, (key, bot.summary())
    report = json.loads((output/'game/result.json').read_text())
    assert_processes_closed(report)
    for i in range(len(bots)):
        journal = [json.loads(line) for line in (output/f'game/session/client-{i}/api.jsonl').read_text().splitlines()]
        assert next(e for e in journal if e['request'] == 'join_game')['raw_affects_selection'] is raw_selection
        assert not any(e['request'] == 'debug' for e in journal)
        if realtime:
            assert not any(e['request'] == 'step' for e in journal)
    native = json.loads((output/'game/session/native-session.json').read_text())
    if native['observation_guard_required']:
        assert all(p['observation_guard']['applied'] for p in native['processes'])
    else:
        assert not native['observation_guard_required']
    return {'results': [r.name for r in results], 'bots': metrics, 'owned_processes_closed': True,
            'realtime': realtime, 'expansion_required': require_expansion}


async def arena_check(output):
    bots = [CombatBot() for _ in range(5)]
    players = [Bot(Race.Terran, b) for b in bots]
    match = GameMatch('MPSC2TeamArena', players, realtime=True, team_ids=[11,22,33,44,55],
                     game_time_limit=60, random_seed=11, output_dir=output/'game', save_replay_as=output/'game.SC2Replay')
    result = (await run_multiple_games_async([match]))[0]
    metrics = [{'hidden_at_start': b.hidden_at_start, 'steps': b.steps, 'events': dict(b.events), 'result': b.result} for b in bots]
    write(output/'bots.json', metrics)
    for bot, player in zip(bots, players):
        assert bot.hidden_at_start and bot.steps > 0 and bot.result == result[player].name
        assert all(bot.events[key] for key in ['damage','destroyed','entered_vision']), metrics
    report = json.loads((output/'game/result.json').read_text())
    assert_processes_closed(report)
    return {'bots': metrics, 'owned_processes_closed': True}


async def failure_check(output):
    records = []
    for cancel in (False, True):
        entered = asyncio.Event()
        class FailingBot(BotAI):
            async def on_step(self, iteration):
                entered.set()
                if cancel:
                    await asyncio.Event().wait()
                raise ValueError('intentional release-test policy failure')
        class IdleBot(BotAI):
            async def on_step(self, iteration):
                pass
        folder = output/('cancel' if cancel else 'exception')
        task = asyncio.create_task(run_game_async('MPSC2TeamArena', [Bot(Race.Terran, FailingBot()), Bot(Race.Terran, IdleBot())],
                                   output_dir=folder, game_time_limit=20))
        if cancel:
            # Wake on either policy entry or an early startup failure, draining
            # the waiter too; never leave an orphan waiting on a failed launch.
            waiter = asyncio.create_task(entered.wait())
            done, _ = await asyncio.wait([task, waiter], timeout=180, return_when=asyncio.FIRST_COMPLETED)
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
            if task in done:
                await task
                raise AssertionError('Expected to reach policy callback before cancellation')
            task.cancel()
        expected = asyncio.CancelledError if cancel else ValueError
        try:
            await asyncio.wait_for(task, 180)
        except expected as error:
            if not cancel:
                assert 'intentional release-test' in str(error)
        else:
            raise AssertionError('Expected policy failure/cancellation to propagate')
        report = json.loads((folder/'result.json').read_text())
        assert report['status'] == 'failed' and 'results' not in report
        assert_processes_closed(report)
        records.append({'case':folder.name, 'error':report['error'], 'owned_processes_closed':True})
    return records


async def standard_check(output, standard_map):
    assert standard_map is not None, '--standard-map is required for this phase'
    class StandardBot(BotAI):
        async def on_start(self):
            self.steps = 0
        async def on_step(self, iteration):
            self.steps += 1
            await self.distribute_workers()
            self.train(U.SCV)
        async def on_end(self, result):
            self.result = result.name
    ai = StandardBot()
    result = await run_game_async(standard_map, [Bot(Race.Terran, ai), Computer(Race.Terran)],
                                 game_time_limit=30, save_replay_as=output/'game.SC2Replay')
    assert ai.steps > 0 and ai.result == result.name and ai.state.score.collected_minerals > 0
    second = StandardBot()
    player = Bot(Race.Terran, second)
    batch = await run_multiple_games_async([GameMatch(standard_map, [player, Computer(Race.Terran)], game_time_limit=20)])
    assert batch[0][player].name == second.result and second.steps > 0
    from unittest.mock import patch
    from mpsc2.portconfig import Portconfig
    allocated = []
    class TrackedPorts(Portconfig):
        def __init__(self):
            super().__init__()
            allocated.append(self)
    pair = [StandardBot(), StandardBot()]
    with patch('mpsc2.standard.Portconfig', TrackedPorts):
        pair_results = await run_game_async(standard_map, [Bot(Race.Terran, b) for b in pair], game_time_limit=20)
    assert all(b.steps > 0 and b.result == r.name for b,r in zip(pair,pair_results))
    assert len(allocated) == 1 and allocated[0]._picked_ports == []
    return {'async_result':result.name, 'async_steps':ai.steps, 'standard_batch_result':second.result,
            'batch_steps':second.steps, 'async_pair_results':[r.name for r in pair_results], 'allocated_ports_released':True}


async def replay_check(output, replay):
    assert replay is not None, '--replay is required for this phase'
    records = []
    for observed in (0, 3):
        ai = AuditObserver()
        result = await run_replay_async(ai, replay, observed_id=observed, step_size=224)
        assert len(result) >= 4 and ai.steps > 0 and ai.ended
        assert ai.observed_player_id == observed
        assert ai.result == (result[observed].name if observed else None)
        records.append({'observed_id':observed,'steps':ai.steps,'max_structures':ai.max_structures,'callback_result':ai.result,
                        'results':{pid:r.name for pid,r in result.items()}})
    ai = AuditObserver()
    result = await run_replay_async(ai, replay, observed_id=0, realtime=True, speed=4, step_size=8, max_game_loop=64)
    assert result == {} and ai.ended and ai.result is None and ai.steps > 0
    records.append({'paced_preview':True,'steps':ai.steps,'results':{}})
    return records


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--phase', choices=['races','arena','failures','standard','replay'], required=True)
    parser.add_argument('--standard-map', type=Path)
    parser.add_argument('--replay', type=Path)
    parser.add_argument('--raw-selection', action='store_true', help='Enable raw_affects_selection in the mixed-race probe')
    parser.add_argument('--realtime', action='store_true', help='Run the race/research phase in realtime')
    parser.add_argument('--step-size', type=int, default=112, help='Race probe cadence in loops; use 32 for the original crash fixture')
    parser.add_argument('--research-only', action='store_true', help='Require normal economy, production and research; report expansion without requiring it')
    parser.add_argument('--races', nargs='+', choices=['Terran','Protoss','Zerg','Random'],
                        default=['Terran','Protoss','Zerg','Random'], help='Race probe roster, 2..8 players')
    parser.add_argument('--skip-research', action='store_true', help='Run the production-only control without upgrades')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    checks = {'races':lambda out: race_check(out,args.raw_selection,tuple(Race[name] for name in args.races),not args.skip_research,args.realtime,args.step_size,not args.research_only),
              'arena':arena_check,'failures':failure_check,
              'standard':lambda out: standard_check(out,args.standard_map),
              'replay':lambda out: replay_check(out,args.replay)}
    try:
        detail = await checks[args.phase](args.output)
    except BaseException as error:
        write(args.output/'validation.json', {'phase':args.phase,'passed':False,'error':f'{type(error).__name__}: {error}'})
        raise
    write(args.output/'validation.json', {'phase':args.phase,'passed':True,'detail':detail})
    print(f'VALIDATED release phase: {args.phase}', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
