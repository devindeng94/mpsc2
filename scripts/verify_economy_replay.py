"""Independently verify production and results from a full-game SC2Replay.

Requires the dev extra (sc2reader). Local API replays lack Battle.net cache
handles, so read the actual tracker stream without sc2reader's lobby loader.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

import sc2reader


def verify(output: Path) -> dict:
    replay_path = output / 'game.SC2Replay'
    result = json.loads((output / 'result.json').read_text())
    player_ids = [p['player_id'] for p in result['players']]
    count = len(player_ids)
    if not 2 <= count <= 8 or len(set(player_ids)) != count:
        raise ValueError('Expected 2..8 distinct native players in result.json')
    replay = sc2reader.resources.Replay(str(replay_path), load_level=0)
    try:
        name = 'replay.tracker.events'
        replay._read_data(name, replay._get_reader(name))
        events = replay.raw_data[name]
        metadata = json.loads(replay.archive.read_file('replay.gamemetadata.json'))
    finally:
        replay.archive.file.close()
    units = {}
    born = {pid: Counter() for pid in player_ids}
    completed = {pid: Counter() for pid in player_ids}
    construction_loops = {pid: [] for pid in player_ids}
    last_stats = {}
    for event in events:
        if event.name in ('UnitBornEvent', 'UnitInitEvent'):
            units[event.unit_id] = event
            if event.name == 'UnitBornEvent' and event.control_pid in born:
                born[event.control_pid][event.unit_type_name] += 1
        elif event.name == 'UnitDoneEvent':
            start = units[event.unit_id]
            if start.control_pid in completed:
                completed[start.control_pid][start.unit_type_name] += 1
                construction_loops[start.control_pid].append(event.frame - start.frame)
        elif event.name == 'PlayerStatsEvent':
            last_stats[event.pid] = {
                'loop': event.frame, 'minerals': event.minerals_current,
                'vespene': event.vespene_current, 'workers': event.workers_active_count,
            }
    expected_results = dict(zip([p['player_id'] for p in result['players']], result['results']))
    replay_results = {p['PlayerID']: {'Win':'Victory', 'Loss':'Defeat', 'Tie':'Tie'}[p['Result']] for p in metadata['Players']}
    checks = {'results_match_all_clients': replay_results == expected_results,
              'native_win_and_loss': set(replay_results.values()) == {'Victory', 'Defeat'}}
    session = json.loads((output / 'session/native-session.json').read_text())
    checks['independent_clients'] = (
        len(session['processes']) == len(set(session['player_ids'])) == count
        and len({p['pid'] for p in session['processes']}) == count
        and len({p['api_port'] for p in session['processes']}) == count
        and (count == 2 and session['stock_create_error']['code'] == 0
             or count > 2 and session['promotion']['agents'] == count and session['promotion']['computers'] == 0))
    requests = Counter()
    for i in range(count):
        for line in (output / f'session/client-{i}/api.jsonl').read_text().splitlines():
            requests[json.loads(line)['request']] += 1
    checks['no_debug_requests'] = requests['debug'] == 0
    if result['realtime']:
        checks['realtime_without_manual_steps'] = requests['step'] == 0
    players = []
    for p in result['players']:
        pid = p['player_id']
        checks[f'player_{pid}_production'] = (
            born[pid]['SCV'] > 12 and born[pid]['Marine'] > 0 and born[pid]['Marauder'] > 0
            and all(completed[pid][t] > 0 for t in ('SupplyDepot', 'Barracks', 'Refinery', 'BarracksTechLab', 'CommandCenter'))
            and len(construction_loops[pid]) >= 4 and min(construction_loops[pid]) > 0
        )
        players.append({'player_index': p['index'], 'player_id': pid, 'born_including_initial': dict(born[pid]),
                        'completed': dict(completed[pid]), 'construction_durations_loops': construction_loops[pid],
                        'last_stats': last_stats.get(pid)})
    report = {'passed': all(checks.values()), 'checks': checks,
              'duration_loops': replay.frames, 'duration_faster_seconds': round(replay.frames / 22.4, 2),
              'metadata_duration_normal_seconds': metadata['Duration'], 'request_counts': dict(requests),
              'replay_results': replay_results, 'players': players}
    (output / 'replay-verification.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    report = verify(parser.parse_args().output)
    print(json.dumps(report, indent=2))
    if not report['passed']:
        raise SystemExit('Replay verification failed')
