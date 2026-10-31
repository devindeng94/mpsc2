"""Verify native research tracker events; optionally replay upgrades and effects.

Usage: python scripts/verify_research_replay.py reports/races-run --playback
Input is the output directory of validate_alpha.py --phase races.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import json
import os
from pathlib import Path

import sc2reader

from mpsc2 import run_replay_async
from mpsc2.ids.upgrade_id import UpgradeId
from mpsc2.observer_ai import ObserverAI

UPGRADES = {'Terran': 'TerranInfantryWeaponsLevel1', 'Protoss': 'ProtossGroundWeaponsLevel1',
            'Zerg': 'zerglingmovementspeed'}


class ResearchObserver(ObserverAI):
    async def on_start(self):
        self.upgrades = set()
        self.events = Counter()
        self.attack_levels = {}

    async def on_upgrade_complete(self, upgrade):
        self.events[upgrade.name] += 1

    async def on_step(self, iteration):
        self.upgrades.update(u.name for u in self.state.upgrades)
        for unit in self.state.observation_raw.units:
            self.attack_levels[unit.owner] = max(self.attack_levels.get(unit.owner, 0), unit.attack_upgrade_level)

    async def on_end(self, result):
        self.result = result.name if result is not None else None


async def verify(output: Path, playback: bool) -> dict:
    game = json.loads((output/'game/result.json').read_text())
    bots = json.loads((output/'bots.json').read_text())
    expected = {p['player_id']: UPGRADES[b['race']] for p, b in zip(game['players'], bots)}
    results = {p['player_id']: r for p, r in zip(game['players'], game['results'])}
    assert game['status'] == 'completed' and len(set(expected)) == len(bots)
    session = json.loads((output/'game/session/native-session.json').read_text())
    assert len({p['pid'] for p in session['processes']}) == len(bots)
    assert len({p['api_port'] for p in session['processes']}) == len(bots)
    for player, bot in zip(game['players'], bots):
        assert bot['history'] == ['before_start', 'start', 'end'] and bot['max_workers'] > 12
        worker, army, production, gas = {
            'Terran': ('SCV', 'MARINE', 'BARRACKS', 'REFINERY'),
            'Protoss': ('PROBE', 'ZEALOT', 'GATEWAY', 'ASSIMILATOR'),
            'Zerg': ('DRONE', 'ZERGLING', 'SPAWNINGPOOL', 'EXTRACTOR'),
        }[bot['race']]
        assert all(bot['events'].get(key, 0) > 0 for key in (
            'created_'+worker, 'created_'+army, 'complete_'+production, 'complete_'+gas))
        assert bot['events']['upgrade_'+expected[player['player_id']].upper()] == 1
        assert bot['collected'][0] > 1000 and bot['collected'][1] > 100
        try:
            os.kill(player['pid'], 0)
        except ProcessLookupError:
            pass
        else:
            raise AssertionError(f"Owned process still exists: {player['pid']}")
    requests = Counter()
    for i in range(len(bots)):
        for line in (output/f'game/session/client-{i}/api.jsonl').read_text().splitlines():
            requests[json.loads(line)['request']] += 1
    assert requests['debug'] == 0
    if game['realtime']:
        assert requests['step'] == 0
    if len(bots) > 2:
        assert all(p['observation_guard']['applied'] and p['observation_guard']['pid'] == p['pid'] for p in session['processes'])
    path = output/'game.SC2Replay'
    replay = sc2reader.resources.Replay(str(path), load_level=0)
    try:
        name = 'replay.tracker.events'
        replay._read_data(name, replay._get_reader(name))
        completions = [{'player_id': e.pid, 'upgrade': e.upgrade_type_name, 'loop': e.frame, 'count': e.count}
                       for e in replay.raw_data[name] if e.name == 'UpgradeCompleteEvent'
                       and e.pid in expected and e.upgrade_type_name == expected[e.pid]]
        metadata = json.loads(replay.archive.read_file('replay.gamemetadata.json'))
    finally:
        replay.archive.file.close()
    assert {e['player_id'] for e in completions if e['loop'] > 0 and e['count'] == 1} == set(expected)
    native_results = {p['PlayerID']: {'Win': 'Victory', 'Loss': 'Defeat', 'Tie': 'Tie'}[p['Result']]
                      for p in metadata['Players']}
    assert native_results == results
    observations = []
    if playback:
        # All-player view checks visible weapon effects; highest ID exercises
        # the formerly underflowing selected-player replay path.
        for observed in (0, max(expected)):
            ai = ResearchObserver()
            played = await run_replay_async(ai, path, observed_id=observed, step_size=224)
            assert {p: r.name for p, r in played.items()} == results
            if observed:
                upgrade = UpgradeId[expected[observed].upper()].name
                assert upgrade in ai.upgrades and ai.events[upgrade] == 1
                assert ai.result == results[observed]
            else:
                for p, bot in zip(game['players'], bots):
                    if bot['race'] in ('Terran', 'Protoss'):
                        assert ai.attack_levels.get(p['player_id'], 0) >= 1
            observations.append({'observed_id': observed, 'upgrades': sorted(ai.upgrades),
                                 'upgrade_events': dict(ai.events), 'attack_levels': ai.attack_levels,
                                 'result': ai.result})
    report = {'passed': True, 'native_results': native_results, 'research_completions': completions,
              'playback': observations, 'request_counts': dict(requests),
              'independent_clients': True, 'own_upgrade_callbacks': True, 'owned_processes_closed': True}
    (output/'research-replay-verification.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--playback', action='store_true', help='Launch SC2 to verify observed upgrades and weapon effects')
    args = parser.parse_args()
    print(json.dumps(asyncio.run(verify(args.output, args.playback)), indent=2))
