import hashlib
import importlib.util
from pathlib import Path

import mpyq
import pytest
from sc2.ids.unit_typeid import UnitTypeId as U
from s2clientprotocol import raw_pb2 as raw, sc2api_pb2 as api

from mpsc2.arena import MELEE_SHA256, melee_positions, prepare_map, validate_map
from mpsc2.main import _check_setup

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / 'maps/MPSC2Melee.SC2Map'


def test_economy_fixture_rebuilds_exactly(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    from build_melee_map import build_melee
    output = build_melee(tmp_path / 'melee.SC2Map')
    assert output.read_bytes() == MAP.read_bytes()
    assert hashlib.sha256(output.read_bytes()).hexdigest() == MELEE_SHA256
    assert validate_map(output) == 'melee'


@pytest.mark.parametrize('realtime', [False, True])
def test_economy_map_uses_native_initialization_and_dynamic_building_victory(tmp_path, realtime):
    path = prepare_map(MAP, tmp_path / 'game.SC2Map', [7, 9, 7, 9], 600, realtime=realtime)
    archive = mpyq.MPQArchive(str(path))
    try:
        script = archive.read_file('MapScript.galaxy').decode()
        assert script.count('ResourceBase(') == 9  # definition plus eight mineral/gas bases
        assert 'MeleeInitResourcesForPlayer(p, PlayerRace(p))' in script
        assert 'MeleeInitUnitsForPlayer(p, PlayerRace(p), Point(x, y))' in script
        assert 'c_targetFilterStructure, c_unitFilterRequired' in script
        assert 'c_targetFilterDead, c_unitFilterExcluded' in script
        assert 'if (slots[p] == 3) { StartBase(p, 30.5, 85.5); }' in script
        assert 'if (slots[p] == 2) { StartBase(p, 97.5, 30.5); }' in script
        assert 'UnitCreate(6, "Marine"' not in script
        assert 'REALTIME_MODE' not in script and 'TIME_LIMIT' not in script
        assert 'TimerStart(matchTimer, 600.0000, false, c_timeGame)' in script
    finally:
        archive.file.close()


def test_economy_spawns_follow_input_team_ids():
    positions = melee_positions([7, 9, 7, 9])
    assert positions[1][0] == positions[3][0] < positions[2][0] == positions[4][0]
    assert len(set(positions.values())) == 4


def test_displaced_base_is_rejected_before_bot_startup():
    obs, ids, teams = melee_observations()
    base = next(u for u in obs[0].observation.observation.raw_data.units if u.unit_type == U.COMMANDCENTER.value)
    base.pos.y += 3
    with pytest.raises(RuntimeError, match='was displaced'):
        _check_setup(obs, ids, teams, False, 'melee')


def melee_observations():
    ids, teams = [1, 4, 3, 2], [7, 9, 7, 9]
    responses = []
    for pid, team in zip(ids, teams):
        response = api.Response()
        obs = response.observation.observation
        obs.player_common.player_id = pid
        obs.player_common.minerals = 50
        for owner, owner_team in zip(ids, teams):
            if owner_team != team:
                continue
            alliance = raw.Self if pid == owner else raw.Ally
            base = obs.raw_data.units.add(owner=owner, alliance=alliance, unit_type=U.COMMANDCENTER.value)
            base.pos.x, base.pos.y = melee_positions(teams)[ids.index(owner)+1]
            for _ in range(12):
                obs.raw_data.units.add(owner=owner, alliance=alliance, unit_type=U.SCV.value)
        responses.append(response)
    return responses, ids, teams


def test_economy_startup_checks_fog_alliances_and_normal_resources():
    obs, ids, teams = melee_observations()
    evidence = _check_setup(obs, ids, teams, False, 'melee')
    assert evidence[0]['unit_counts'] == {1: 13, 3: 13}
    obs[0].observation.observation.player_common.minerals = 50000
    with pytest.raises(RuntimeError, match='initial resources'):
        _check_setup(obs, ids, teams, False, 'melee')


def test_economy_startup_rejects_missing_allied_base():
    obs, ids, teams = melee_observations()
    units = obs[0].observation.observation.raw_data.units
    del units[13]
    with pytest.raises(RuntimeError, match='starting base/workers'):
        _check_setup(obs, ids, teams, False, 'melee')


def test_economy_evidence_rejects_attempts_without_completed_production(tmp_path):
    spec = importlib.util.spec_from_file_location('full_game', ROOT / 'examples/full_game.py')
    example = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(example)
    import json
    for i in range(4):
        (tmp_path / f'player-{i}.json').write_text(json.dumps({
            'player_index': i, 'player_id': i+1, 'team_id': i//2, 'result': 'Tie',
            'initial': {'workers': 12, 'townhalls': 1, 'minerals': 50, 'vespene': 0, 'army': 0},
            'trained': {}, 'completed': {}, 'construction_started_and_completed': 0, 'action_errors': {},
            'snapshots': [{'collected_minerals': 5000, 'collected_vespene': 1000, 'spent_minerals': 2000,
                           'spent_vespene': 500, 'killed_units': 0, 'killed_structures': 0}],
        }))
    report = example.validate_economy(tmp_path)
    assert not report['passed']
    for player in report['players']:
        assert player['checks']['mined_minerals_and_gas']
        assert not player['checks']['completed_production_chain']
        assert not player['checks']['trained_workers_and_army']


def test_resource_snapshots_deduplicated_without_mutating_raw_evidence():
    from unittest.mock import patch
    from mpsc2.main import _game_state
    response = api.Response()
    units = response.observation.observation.raw_data.units
    # Different native tags represent the same physical mineral field.
    for tag, display, x, alliance, unit_type in [
        (10, raw.Snapshot, 24, raw.Neutral, U.MINERALFIELD.value),
        (20, raw.Visible, 24, raw.Neutral, U.MINERALFIELD.value),
        (30, raw.Snapshot, 47, raw.Neutral, U.MINERALFIELD.value),
        (40, raw.Snapshot, 24, raw.Enemy, U.MARINE.value),
    ]:
        unit = units.add(tag=tag, alliance=alliance, display_type=display, unit_type=unit_type)
        unit.pos.x, unit.pos.y = x, 30
    before = response.SerializeToString()
    with patch('mpsc2.main.GameState', side_effect=lambda observation: observation):
        clean = _game_state(response)
    assert [u.tag for u in clean.observation.raw_data.units] == [20, 30, 40]
    assert response.SerializeToString() == before
