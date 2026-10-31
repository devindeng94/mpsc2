import asyncio
from dataclasses import FrozenInstanceError
import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sc2.bot_ai import BotAI
from sc2.data import Race, Result
from sc2.player import Bot, Computer
from sc2.units import Units

import mpsc2
from mpsc2 import GameMatch, maps, TeamInfo, allied_units
from mpsc2.main import run_match


@pytest.mark.parametrize('module,symbol', [
    ('bot_ai', 'BotAI'), ('bot_ai_internal', 'BotAIInternal'), ('unit', 'Unit'),
    ('units', 'Units'), ('player', 'Bot'), ('player', 'Computer'), ('player', 'Human'),
    ('player', 'BotProcess'), ('data', 'Race'), ('data', 'Result'), ('position', 'Point2'),
    ('position', 'Point3'), ('game_state', 'GameState'), ('client', 'Client'),
    ('observer_ai', 'ObserverAI'), ('ids.unit_typeid', 'UnitTypeId'),
    ('ids.ability_id', 'AbilityId'), ('ids.upgrade_id', 'UpgradeId'), ('ids.buff_id', 'BuffId'),
    ('ids.effect_id', 'EffectId'), ('dicts.unit_trained_from', 'UNIT_TRAINED_FROM'),
    ('game_data', 'GameData'), ('game_info', 'GameInfo'), ('portconfig', 'Portconfig'),
])
def test_upstream_class_and_enum_identity(module, symbol):
    assert getattr(importlib.import_module(f'mpsc2.{module}'), symbol) is getattr(importlib.import_module(f'sc2.{module}'), symbol)


def test_all_compatibility_modules_import_without_game():
    root = Path(mpsc2.__file__).parent
    for path in root.rglob('*.py'):
        if path.name == '__main__.py':
            continue
        module = '.'.join(path.relative_to(root.parent).with_suffix('').parts)
        importlib.import_module(module)


def test_packaged_maps_work_without_sc2_installation_and_match_sources(monkeypatch, tmp_path):
    import sc2.maps
    class NoInstallation:
        @property
        def MAPS(self):
            raise AssertionError('Must not consult SC2 installation for a bundled/absolute map')
    monkeypatch.setattr(sc2.maps, 'Paths', NoInstallation())
    monkeypatch.chdir(tmp_path)
    root = Path(__file__).resolve().parents[1]
    for name in maps.available():
        game_map = maps.get(name)
        assert isinstance(game_map, sc2.maps.Map)
        assert game_map.path.is_absolute()
        assert game_map.data == (root / 'maps' / f'{name}.SC2Map').read_bytes()
        assert maps.get(game_map.path).relative_path == game_map.path
        assert maps.get(f'{name}.SC2Map').path == game_map.path
    with pytest.raises(FileNotFoundError):
        maps.get(tmp_path / 'absent.SC2Map')


def bots(n=4):
    return [Bot(Race.Terran, BotAI()) for _ in range(n)]


def test_standard_dispatch_preserves_upstream_arguments_and_scalar_result(tmp_path):
    path = tmp_path / 'standard.SC2Map'
    path.write_bytes(b'fixture: not a multiplayer map')
    players = [bots(1)[0], Computer(Race.Zerg)]
    with patch('sc2.main.run_game', return_value=Result.Victory) as upstream:
        result = mpsc2.run_game(path, players, True, 'ports', tmp_path / 'game.SC2Replay', 30, 'rgb', 7, 'version', True)
    assert result is Result.Victory
    args = upstream.call_args.args
    assert args[0].path == path
    assert args[1:] == (players, True, 'ports', str(tmp_path / 'game.SC2Replay'), 30, 'rgb', 7, 'version', True)


def test_async_standard_route_starts_host_and_guest_together(tmp_path):
    path = tmp_path / 'standard.SC2Map'
    path.write_bytes(b'fixture')
    async def exercise():
        ready = asyncio.Event()
        async def host(*args, **kwargs):
            await ready.wait()
            return Result.Victory
        async def guest(*args, **kwargs):
            ready.set()
            return Result.Defeat
        with patch('sc2.main._host_game', side_effect=host) as h, patch('sc2.main._join_game', side_effect=guest) as g, patch('mpsc2.standard.Portconfig'):
            assert await asyncio.wait_for(mpsc2.run_game_async(path, bots(2)), 2) == [Result.Victory, Result.Defeat]
            assert h.call_args.kwargs['portconfig'] is g.call_args.kwargs['portconfig']
    asyncio.run(exercise())


def test_default_ffa_and_melee_time_limit_reach_native_backend():
    with patch('mpsc2.main._run_multiplayer_game_async', new_callable=AsyncMock, return_value=[Result.Tie]*4) as native:
        assert mpsc2.run_game('MPSC2Melee', bots()) == [Result.Tie]*4
        assert native.call_args.kwargs['team_ids'] == (0, 1, 2, 3)
        assert native.call_args.kwargs['game_time_limit'] == 900


@pytest.mark.parametrize('options', [{'sc2_version': 'x'}, {'portconfig': object()}, {'rgb_render_config': {}}])
def test_native_unsupported_options_rejected_before_launch(options):
    with patch('mpsc2.main.NativeMultiplayerSession') as native:
        with pytest.raises(NotImplementedError):
            mpsc2.run_game('MPSC2TeamArena', bots(), **options)
        native.assert_not_called()


def test_standard_cannot_deadlock_on_multiplayer_map():
    with patch('sc2.main.run_game') as upstream:
        with pytest.raises(ValueError, match='require 2..8'):
            mpsc2.run_game('MPSC2TeamArena', [bots(1)[0], Computer(Race.Terran)])
        upstream.assert_not_called()


def test_team_metadata_is_immutable_and_uses_native_ids():
    source = {1: 7, 4: 9, 2: 7, 3: 9}
    team = TeamInfo(1, 0, 7, source)
    source[2] = 9
    assert team.ally_player_ids == (2,)
    assert team.enemy_player_ids == (4, 3)
    with pytest.raises(TypeError):
        team.team_ids[2] = 10
    with pytest.raises(FrozenInstanceError):
        team.team_id = 11


def test_allied_units_separates_self_enemies_and_buildings():
    units = [SimpleNamespace(alliance=a, is_structure=s) for a, s in [(1, False), (2, False), (2, True), (4, False)]]
    ai = SimpleNamespace(all_units=Units(units, None))
    assert list(allied_units(ai)) == [units[1]]
    assert list(allied_units(ai, structures=True)) == [units[2]]


def test_batch_maps_results_to_player_objects_and_stops_on_failure():
    matches = [GameMatch('MPSC2TeamArena', bots(), team_ids=[7, 9, 7, 9]) for _ in range(3)]
    expected = [Result.Victory, Result.Defeat, Result.Victory, Result.Defeat]
    with patch('mpsc2.main.run_game_async', new_callable=AsyncMock, return_value=expected) as run:
        results = mpsc2.run_multiple_games(matches)
        assert len(results) == 3
        assert list(results[1].keys()) == matches[1].players
        assert list(results[1].values()) == expected
        assert all(c.kwargs['output_dir'] is None for c in run.call_args_list)
    with patch('mpsc2.main.run_game_async', new_callable=AsyncMock, side_effect=[expected, RuntimeError('policy failure'), expected]) as run:
        with pytest.raises(RuntimeError, match='policy failure'):
            mpsc2.run_multiple_games(matches)
        assert run.await_count == 2


def test_standard_batch_keeps_botprocess_configuration(tmp_path):
    path = tmp_path / 'standard.SC2Map'
    path.write_bytes(b'fixture')
    players = bots(2)
    config = [{'host': '127.0.0.1'}]
    match = GameMatch(path, players, sc2_config=config)
    with patch('sc2.main.a_run_multiple_games', new_callable=AsyncMock, return_value=[dict(zip(players, [Result.Tie]*2))]) as run:
        assert len(mpsc2.run_multiple_games([match])) == 1
        assert run.call_args.args[0][0].sc2_config == config


def test_external_run_match_rejects_four_clients():
    with pytest.raises(NotImplementedError, match='fresh sessions'):
        asyncio.run(run_match([], GameMatch('MPSC2TeamArena', bots())))


def test_diagnostics_on_unsupported_platform_do_not_launch(monkeypatch):
    monkeypatch.setenv('SC2PATH', '/nonexistent/mpsc2-sc2-fixture')
    with patch('mpsc2.capabilities.platform.system', return_value='Linux'):
        info = mpsc2.get_capabilities()['multiplayer']
    assert not info['ready']
    assert not info['checks']['executable_present']
    assert info['checks']['bundled_maps']


def test_main_entrypoints_are_available():
    from mpsc2 import main
    for name in ['run_game', 'run_game_async', 'GameMatch', 'run_multiple_games', 'a_run_multiple_games', 'run_replay', 'get_replay_version']:
        assert getattr(main, name) is getattr(mpsc2, name)
