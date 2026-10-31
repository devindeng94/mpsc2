"""Opt-in live engine matrix for 2..8 independent clients, with replay evidence.

python scripts/validate_player_counts.py --counts 2 3 4 5 6 7 8 --output reports/counts-new
Add --realtime to validate automatic advancement; --scenario melee checks economy.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

import mpyq
from mpsc2 import allied_units, run_game
from mpsc2.bot_ai import BotAI
from mpsc2.data import Race
from mpsc2.ids.unit_typeid import UnitTypeId as U
from mpsc2.player import Bot


class CountBot(BotAI):
    def __init__(self, scenario):
        super().__init__()
        self.scenario = scenario
        self.steps = 0
        self.collected = 0
        self.max_workers = 0
        self.max_structures = 0
        self.moved = False
        self.ended = False

    async def on_start(self):
        self.roster = sorted(self.game_info.player_races)
        self.initial_positions = {u.tag: u.position for u in self.units}
        self.owned_tags = set(self.initial_positions)
        assert self.roster == list(range(1, len(self.team_ids) + 1))
        assert self.team.ally_player_ids == self.ally_player_ids
        assert allied_units(self).amount == (12 if self.scenario == 'melee' else 6) * len(self.ally_player_ids)

    async def on_step(self, iteration):
        self.steps += 1
        self.collected = max(self.collected, self.state.score.collected_minerals)
        self.max_workers = max(self.max_workers, self.workers.amount)
        self.max_structures = max(self.max_structures, self.structures.amount)
        self.moved |= any(u.tag in self.initial_positions and u.distance_to(self.initial_positions[u.tag]) > 0.5 for u in self.units)
        if self.scenario == 'arena':
            if iteration == 0:
                for unit in self.units:
                    unit.move(unit.position.towards(self.game_info.map_center, 2))
        else:
            if iteration % 4 == 0:
                await self.distribute_workers()
            for base in self.townhalls.ready.idle:
                if self.workers.amount < 15 and self.can_afford(U.SCV):
                    base.train(U.SCV)
            if not self.structures(U.SUPPLYDEPOT) and not self.already_pending(U.SUPPLYDEPOT) and self.can_afford(U.SUPPLYDEPOT):
                await self.build(U.SUPPLYDEPOT, near=self.start_location.towards(self.game_info.map_center, 7))

    async def on_end(self, result):
        self.ended = True
        self.result = result.name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--counts', nargs='+', type=int, choices=range(2, 9), default=list(range(2, 9)))
    parser.add_argument('--realtime', action='store_true')
    parser.add_argument('--sc2-version', help='Select a registered native profile explicitly')
    parser.add_argument('--scenario', choices=['arena', 'melee'], default='arena')
    parser.add_argument('--seconds', type=float)
    parser.add_argument('--step-size', type=int, default=8)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    evidence = []
    for count in args.counts:
        folder = args.output / str(count)
        bots = [CountBot(args.scenario) for _ in range(count)]
        # Interleaved groups exercise input-index versus native-ID mapping.
        teams = [i % 2 for i in range(count)]
        results = run_game(
            'MPSC2Melee' if args.scenario == 'melee' else 'MPSC2TeamArena',
            [Bot(Race.Terran, bot) for bot in bots], team_ids=teams,
            realtime=args.realtime, game_time_limit=args.seconds or (60 if args.scenario == 'melee' else 5),
            step_size=args.step_size, random_seed=37, disable_fog=True, sc2_version=args.sc2_version,
            output_dir=folder, save_replay_as=folder / 'game.SC2Replay',
        )
        report = json.loads((folder / 'result.json').read_text())
        metrics = [{'steps': b.steps, 'moved': b.moved, 'collected_minerals': b.collected,
                    'max_workers': b.max_workers, 'max_structures': b.max_structures,
                    'ended': b.ended, 'result': getattr(b, 'result', None)} for b in bots]
        (folder/'bot-metrics.json').write_text(json.dumps(metrics, indent=2)+'\n')
        assert len(set().union(*(b.owned_tags for b in bots))) == sum(len(b.owned_tags) for b in bots)
        for key in ('player_id', 'pid', 'api_port'):
            assert len({p[key] for p in report['players']}) == count
        journals = []
        for i, bot in enumerate(bots):
            assert bot.steps > 0 and bot.ended and bot.result == results[i].name and bot.moved, (i, metrics[i])
            if args.scenario == 'melee':
                assert bot.collected > 0 and bot.max_workers > 12 and bot.max_structures > 1, (i, metrics[i])
            requests = Counter(json.loads(line)['request'] for line in (folder / f'session/client-{i}/api.jsonl').read_text().splitlines())
            assert requests['action'] > 0 and requests['debug'] == 0
            if args.realtime:
                assert requests['step'] == 0
            journals.append(dict(requests))
        archive = mpyq.MPQArchive(str(folder / 'game.SC2Replay'), listfile=False)
        try:
            metadata = json.loads(archive.read_file('replay.gamemetadata.json'))
        finally:
            archive.file.close()
        assert sorted(p['PlayerID'] for p in metadata['Players']) == list(range(1, count + 1))
        item = {'count': count, 'realtime': args.realtime, 'scenario': args.scenario,
                'teams': teams, 'native_ids': [p['player_id'] for p in report['players']],
                'results': [r.name for r in results], 'replay_players': metadata['Players'],
                'bots': metrics,
                'requests': journals}
        evidence.append(item)
        (args.output / 'validation.json').write_text(json.dumps(evidence, indent=2) + '\n')
        print(f'VALIDATED {count} independent players, realtime={args.realtime}, {args.scenario}', flush=True)


if __name__ == '__main__':
    main()
