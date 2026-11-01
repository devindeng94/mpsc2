import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sc2.data import Race, Result
from sc2.observer_ai import ObserverAI
from s2clientprotocol import sc2api_pb2 as api

from mpsc2.replay import _observer_callbacks, _play, _prepare_observer, run_replay, run_replay_async


@pytest.mark.parametrize('event', ['vision_enter', 'vision_leave', 'damage', 'morph'])
def test_real_observer_event_dispatch_handles_missing_upstream_callbacks(event):
    # Exercise the actual inherited dispatchers used in selected-player replays.
    from sc2.ids.unit_typeid import UnitTypeId
    from sc2.units import Units
    ai = ObserverAI()
    previous = SimpleNamespace(tag=1, health=100, shield=0, type_id=UnitTypeId.MARINE)
    current = SimpleNamespace(tag=1, health=50 if event == 'damage' else 100, shield=0,
                              type_id=UnitTypeId.MARAUDER if event == 'morph' else UnitTypeId.MARINE)
    ai.units = Units([current], ai)
    ai._units_previous_map = {1: previous}
    ai._unit_tags_seen_this_game = {1}
    ai.enemy_units = Units([current] if event == 'vision_enter' else [], ai)
    ai.enemy_structures = Units([], ai)
    ai._enemy_units_previous_map = {1: previous} if event == 'vision_leave' else {}
    ai._enemy_structures_previous_map = {}
    with _observer_callbacks(ai):
        asyncio.run(ai._issue_vision_events() if event.startswith('vision') else ai._issue_unit_added_events())
    assert not hasattr(ai, 'on_enemy_unit_entered_vision')
    assert not hasattr(ObserverAI, 'on_unit_took_damage')


def test_observer_adapter_preserves_overrides_and_restores_after_failure():
    ai = ObserverAI()
    callback = ai.on_enemy_unit_entered_vision = AsyncMock(side_effect=ValueError('user callback'))
    with pytest.raises(ValueError, match='user callback'):
        with _observer_callbacks(ai):
            asyncio.run(ai.on_enemy_unit_entered_vision(object()))
    assert ai.on_enemy_unit_entered_vision is callback
    assert not hasattr(ai, 'on_unit_type_changed')


def observation(frame, results=False):
    response = api.Response()
    response.observation.observation.game_loop = frame
    if results:
        for pid in range(1, 5):
            response.observation.player_result.add(player_id=pid, result=api.Victory if pid in (1, 3) else api.Defeat)
    return response


def client_for(observations):
    return SimpleNamespace(observation=AsyncMock(side_effect=observations),
                           get_game_info=AsyncMock(return_value=SimpleNamespace(map_center=(64, 64), player_races={i: 1 for i in range(1, 5)})),
                           obs_move_camera=AsyncMock(), step=AsyncMock(), game_step=4,
                           get_game_data=AsyncMock(), ping=AsyncMock(), _execute=AsyncMock())


def test_preview_steps_without_fabricating_results():
    client = client_for([observation(0), observation(4), observation(6)])
    assert asyncio.run(_play(client, None, 0, False, 1, 1, 6)) == {}
    assert [c.args[0] for c in client.step.call_args_list] == [4, 2]


def test_replay_returns_all_native_results():
    client = client_for([observation(0), observation(4, True)])
    results = asyncio.run(_play(client, None, 0, False, 1, 1, None))
    assert results == {1: Result.Victory, 2: Result.Defeat, 3: Result.Victory, 4: Result.Defeat}


def test_observer_player_id_and_end_callback():
    client = client_for([observation(0), observation(4, True)])
    ai = SimpleNamespace(_initialize_variables=Mock(), _prepare_start=Mock(), _prepare_first_step=Mock(),
                         on_start=AsyncMock(), on_end=AsyncMock(), on_step=AsyncMock(), issue_events=AsyncMock(), _after_step=AsyncMock())
    with patch('mpsc2.replay._prepare_observer'):
        asyncio.run(_play(client, ai, 3, False, 1, 1, None))
    assert ai._prepare_start.call_args.args[1] == 3
    assert ai.observed_player_id == 3
    ai.on_end.assert_awaited_once_with(Result.Victory)
    ai.on_step.assert_awaited_once_with(0)


def test_observer_no_race_restored_even_if_preparation_fails():
    ai = SimpleNamespace(race=Race.NoRace, _prepare_step=Mock(side_effect=RuntimeError('bad data')))
    with patch('mpsc2.main._game_state'):
        with pytest.raises(RuntimeError, match='bad data'):
            _prepare_observer(ai, observation(0), object())
    assert ai.race == Race.NoRace


def test_missing_observed_player_and_stalled_replay_fail():
    with pytest.raises(ValueError, match='absent'):
        asyncio.run(_play(client_for([observation(0)]), None, 7, False, 1, 1, None))
    with pytest.raises(RuntimeError, match='did not advance'):
        asyncio.run(_play(client_for([observation(0), observation(0)]), None, 0, False, 1, 1, None))


@pytest.mark.parametrize('system', ['Darwin', 'Linux'])
def test_playback_uses_explicit_steps_even_when_realtime(tmp_path, system):
    path = tmp_path / 'game.SC2Replay'
    path.write_bytes(b'fixture')
    process = AsyncMock()
    process._arguments = {}
    controller = process.__aenter__.return_value
    controller._execute.return_value = api.Response(start_replay=api.ResponseStartReplay(), status=api.in_replay)
    client = client_for([observation(0), observation(4, True)])
    with patch('mpsc2.replay.get_replay_version', return_value=('Base96883', 'A'*32)), \
         patch('mpsc2.replay.platform.system', return_value=system), \
         patch('mpsc2.replay.OwnedSC2Process', return_value=process), \
         patch('mpsc2.replay.Client', return_value=client), \
         patch('mpsc2.replay.asyncio.sleep', new_callable=AsyncMock) as sleep:
        results = run_replay(None, path, realtime=True)
    assert len(results) == 4
    if system == 'Linux':
        request = controller._execute.call_args.kwargs['start_replay']
        assert not request.realtime and request.replay_data == b'fixture'
        controller.start_replay.assert_not_awaited()
    else:
        assert controller.start_replay.call_args.kwargs['realtime'] is False
    client.step.assert_awaited_once_with(4)
    sleep.assert_awaited_once()
    process.__aexit__.assert_awaited_once()


@pytest.mark.parametrize('system', ['Darwin', 'Linux'])
def test_callback_failure_releases_replay_process(tmp_path, system):
    path = tmp_path / 'game.SC2Replay'
    path.write_bytes(b'fixture')
    process = AsyncMock()
    process._arguments = {}
    process.__aenter__.return_value._execute.return_value = api.Response(
        start_replay=api.ResponseStartReplay(), status=api.in_replay)
    with patch('mpsc2.replay.get_replay_version', return_value=('Base96883', 'A'*32)), \
         patch('mpsc2.replay.platform.system', return_value=system), \
         patch('mpsc2.replay.OwnedSC2Process', return_value=process), \
         patch('mpsc2.replay.Client'), patch('mpsc2.replay._play', new_callable=AsyncMock, side_effect=ValueError('observer failed')):
        with pytest.raises(ValueError, match='observer failed'):
            run_replay(ObserverAI(), path)
    process.__aexit__.assert_awaited_once()


def test_replay_sync_api_guides_async_callers():
    async def exercise():
        with pytest.raises(RuntimeError, match='run_replay_async'):
            run_replay(None, 'ignored.SC2Replay')
    asyncio.run(exercise())
