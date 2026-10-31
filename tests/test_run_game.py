import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import mpyq
import pytest
from sc2.bot_ai import BotAI
from sc2.data import Race, Result
from sc2.player import Bot, Computer
from s2clientprotocol import raw_pb2 as raw, sc2api_pb2 as api

from mpsc2 import run_game, run_game_async
from mpsc2.arena import normalize_teams, prepare_map
from mpsc2.main import _check_setup, _play, _terminal_results

MAP = Path(__file__).resolve().parents[1] / "maps/MPSC2TeamArena.SC2Map"


def bots():
    return [Bot(Race.Terran, BotAI()) for _ in range(4)]


@pytest.mark.parametrize("teams, expected", [
    ([10, -4, 10, -4], (1, 2, 1, 2)),
    ([8, 8, 8, 9], (1, 1, 1, 2)),
    ([4, 3, 2, 1], (1, 2, 3, 4)),
    ([4, 3, 4, 1], (1, 2, 1, 3)),
])
def test_team_labels_follow_input_equality(teams, expected):
    assert normalize_teams(teams) == expected


@pytest.mark.parametrize("options, message", [
    ({"team_ids": [0, 0, 1]}, "one integer"),
    ({"team_ids": [0, 0, True, 1]}, "integer IDs"),
    ({"team_ids": [1, 1, 1, 1]}, "opposing"),
    ({"realtime": "True"}, "realtime must be a bool"),
    ({"step_size": 0}, "step_size"),
    ({"game_time_limit": float("nan")}, "finite positive"),
    ({"timeout": -1}, "finite positive"),
    ({"random_seed": -1}, "uint32"),
    ({"players": [Computer(Race.Terran)] * 4}, "2..8 sc2.player.Bot"),
    ({"players": [Bot(Race.Terran, BotAI())] * 4}, "distinct BotAI"),
])
def test_invalid_configuration_fails_before_start_or_output(tmp_path, options, message):
    args = dict(map_settings=MAP, players=bots(), team_ids=[0, 0, 1, 1], output_dir=tmp_path / "new")
    args.update(options)
    with patch("mpsc2.main.NativeMultiplayerSession") as session:
        with pytest.raises(ValueError, match=message):
            run_game(**args)
        session.assert_not_called()
    assert not (tmp_path / "new").exists()


def test_unknown_map_and_existing_outputs_are_preserved(tmp_path):
    unknown = tmp_path / "unknown.SC2Map"
    unknown.write_bytes(b"user map")
    with pytest.raises(ValueError, match="supports maps/MPSC2TeamArena"):
        run_game(unknown, bots(), team_ids=[0, 0, 1, 1], output_dir=tmp_path / "new")
    assert unknown.read_bytes() == b"user map"
    with pytest.raises(FileExistsError):
        run_game(MAP, bots(), team_ids=[0, 0, 1, 1], output_dir=tmp_path)
    with pytest.raises(FileExistsError, match="overwrite replay"):
        run_game(MAP, bots(), team_ids=[0, 0, 1, 1], output_dir=tmp_path / "new", save_replay_as=unknown)
    assert not (tmp_path / "new").exists()


def test_sync_api_directs_async_callers_to_async_entrypoint():
    async def call():
        with pytest.raises(RuntimeError, match="run_game_async"):
            run_game(MAP, bots(), team_ids=[0, 0, 1, 1])
    asyncio.run(call())


def test_runtime_map_keeps_source_and_contains_team_handshake(tmp_path):
    original = MAP.read_bytes()
    path = prepare_map(MAP, tmp_path / "new.SC2Map", [7, 9, 7, 9], 30)
    archive = mpyq.MPQArchive(str(path))
    try:
        source = archive.read_file("MapScript.galaxy").decode()
        assert 'if (slot == 3) { return 1; }' in source
        assert 'p = EventPlayer();' in source
        assert 'TriggerAddEventChatMessage' in source
        assert 'PlayerSetAlliance(p, c_allianceIdControl, q, false)' in source
        assert 'GameOver(p, result, true, false)' in source
        assert 'TIME_LIMIT' not in source
        assert '// ARMY_SPAWNS' not in source
    finally:
        archive.file.close()
    assert MAP.read_bytes() == original


def observations(ids=(1, 4, 2, 3), teams=(7, 9, 7, 9)):
    responses = []
    for pid, team in zip(ids, teams):
        response = api.Response()
        obs = response.observation.observation
        obs.player_common.player_id = pid
        for owner, owner_team in zip(ids, teams):
            alliance = raw.Self if pid == owner else raw.Ally if team == owner_team else raw.Enemy
            for _ in range(6):
                obs.raw_data.units.add(owner=owner, alliance=alliance)
        responses.append(response)
    return responses


def test_alliance_check_uses_actual_player_ids_not_guest_order():
    obs = observations()
    evidence = _check_setup(obs, [1, 4, 2, 3], [7, 9, 7, 9], True)
    assert evidence[0]["observed_alliances"] == {1: "Self", 4: "Enemy", 2: "Ally", 3: "Enemy"}
    with pytest.raises(RuntimeError, match="Wrong native alliance"):
        _check_setup(obs, [1, 4, 2, 3], [7, 7, 9, 9], True)


def test_results_follow_input_order_and_require_client_agreement():
    obs = observations()
    for o in obs:
        for pid in range(1, 5):
            o.observation.player_result.add(player_id=pid, result=api.Victory if pid <= 2 else api.Defeat)
    assert _terminal_results(obs, [1, 4, 2, 3]) == [Result.Victory, Result.Defeat, Result.Victory, Result.Defeat]
    obs[-1].observation.player_result[0].result = api.Defeat
    with pytest.raises(RuntimeError, match="disagree"):
        _terminal_results(obs, [1, 4, 2, 3])


def test_divergent_step_sizes_fail_before_engine_barrier():
    async def call(awaitables):
        return await asyncio.gather(*awaitables)
    clients = [SimpleNamespace(game_step=step, in_game=True, _execute=AsyncMock()) for step in [8, 8, 16, 8]]
    players = [SimpleNamespace(ai=SimpleNamespace(
        _prepare_step=lambda *a: None, issue_events=AsyncMock(), on_step=AsyncMock(), _after_step=AsyncMock(),
    )) for _ in range(4)]
    session = SimpleNamespace(clients=clients, player_ids=[1, 4, 2, 3], call=call, step=AsyncMock())
    with patch("mpsc2.main.GameState"):
        with pytest.raises(ValueError, match="same integer client.game_step"):
            asyncio.run(_play(session, players, observations(), 120, {}))
    session.step.assert_not_called()


def test_matching_terminal_results_accept_adjacent_stop_frames():
    obs = observations()
    for index, o in enumerate(obs):
        o.observation.observation.game_loop = 371 + index % 2
        for pid in range(1, 5):
            o.observation.player_result.add(player_id=pid, result=api.Tie)
    session = SimpleNamespace(player_ids=[1, 4, 2, 3])
    report = {}
    assert asyncio.run(_play(session, [], obs, 120, report)) == [Result.Tie] * 4
    assert report["client_game_loops"] == [371, 372, 371, 372]


def test_active_simulation_still_requires_identical_frames():
    obs = observations()
    obs[0].observation.observation.game_loop = 8
    session = SimpleNamespace(player_ids=[1, 4, 2, 3])
    with pytest.raises(RuntimeError, match="synchronization"):
        asyncio.run(_play(session, [], obs, 120, {}))


def test_callback_failure_closes_session_and_records_original_error(tmp_path):
    instances = []

    class FakeSession:
        def __init__(self, *a, **kw):
            self.clients = [SimpleNamespace(game_step=8) for _ in range(4)]
            self.player_ids = [1, 4, 2, 3]
            self.native_metadata = {"processes": [{"pid": i + 100, "api_port": i + 8000} for i in range(4)]}
            self.closed = False
            instances.append(self)
        async def __aenter__(self):
            return self
        async def __aexit__(self, *exc):
            self.closed = True
        async def call(self, awaitables):
            return await asyncio.gather(*awaitables)

    async def fail(*args):
        raise ValueError("bad policy startup")

    output = tmp_path / "failure"
    with patch("mpsc2.main.NativeMultiplayerSession", FakeSession), \
         patch("mpsc2.main._configure_teams", AsyncMock(return_value=(observations(), []))), \
         patch("mpsc2.main._initialize_bot", fail):
        with pytest.raises(ValueError, match="bad policy startup"):
            asyncio.run(run_game_async(MAP, bots(), team_ids=[7, 9, 7, 9], output_dir=output))
    assert instances[0].closed
    assert "ValueError: bad policy startup" in (output / "result.json").read_text()
