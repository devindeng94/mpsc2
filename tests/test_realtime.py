import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sc2.data import Result, Status
from sc2.protocol import ProtocolError
from s2clientprotocol import raw_pb2 as raw, sc2api_pb2 as api

from mpsc2.main import _configure_teams, _initialize_bot, _play_realtime
from mpsc2.native_session import NativeFourSession


def observation(pid, loop=0, *, terminal=False):
    response = api.Response()
    obs = response.observation.observation
    obs.player_common.player_id = pid
    obs.game_loop = loop
    for owner in range(1, 5):
        alliance = raw.Self if owner == pid else raw.Ally if (owner - 1) // 2 == (pid - 1) // 2 else raw.Enemy
        for _ in range(6):
            obs.raw_data.units.add(owner=owner, alliance=alliance)
    if terminal:
        for owner in range(1, 5):
            response.observation.player_result.add(player_id=owner, result=api.Tie)
    return response


class Client:
    def __init__(self, pid, game_step):
        self.pid = pid
        self.game_step = game_step
        self._status = Status.in_game
        self._ws = SimpleNamespace(close=AsyncMock())
        self.chat_send = AsyncMock()
        self.requests = []

    @property
    def in_game(self):
        return self._status == Status.in_game

    async def observation(self, game_loop=None):
        self.requests.append(game_loop)
        await asyncio.sleep(0)
        terminal = self._status == Status.ended or (game_loop is not None and game_loop >= 64)
        if terminal:
            self._status = Status.ended
        return observation(self.pid, game_loop or 64, terminal=terminal)


class Session:
    realtime = True
    disable_fog = True
    timeout = 1
    player_ids = [1, 4, 2, 3]

    def __init__(self):
        self.clients = [Client(pid, step) for pid, step in zip(self.player_ids, [8, 16, 12, 8])]
        self.step = AsyncMock(side_effect=AssertionError("Realtime must not send RequestStep"))

    async def call(self, awaitables):
        return await asyncio.gather(*awaitables)

    async def observe(self):
        return [observation(pid) for pid in self.player_ids]


def test_realtime_setup_uses_observations_without_step():
    session = Session()
    _, evidence = asyncio.run(_configure_teams(session, [7, 9, 7, 9]))
    assert len(evidence) == 4
    session.step.assert_not_called()
    for i, client in enumerate(session.clients):
        assert client.requests == [1]
        client.chat_send.assert_awaited_once_with(f"MPSC2-SLOT-{i+1}", False)


def test_realtime_bots_have_independent_cadences_and_slow_callbacks():
    async def exercise():
        session = Session()
        progressed = asyncio.Event()
        calls = [[] for _ in session.clients]

        async def tick(index, client, obs, iteration):
            calls[index].append(iteration)
            if index == 0 and iteration == 0:
                # A lockstep callback barrier would deadlock here.
                await progressed.wait()
            if index == 3 and iteration == 2:
                progressed.set()

        report = {}
        with patch("mpsc2.main._bot_step", tick):
            results = await _play_realtime(session, list(range(4)), [], 120, report)
        assert results == [Result.Tie] * 4
        assert [len(c) for c in calls] == [7, 3, 5, 7]
        assert report["client_iterations"] == [7, 3, 5, 7]
        assert report["client_game_loops"] == [64, 64, 72, 64]
        session.step.assert_not_called()
        for client in session.clients:
            client.chat_send.assert_awaited_once_with("MPSC2-READY", False)
            assert client.requests[0] == client.game_step
            assert all(b > a for a, b in zip(client.requests, client.requests[1:]))
    asyncio.run(exercise())


def test_realtime_match_is_not_limited_to_one_callback_timeout():
    async def exercise():
        session = Session()
        session.timeout = 0.05

        async def tick(*args):
            await asyncio.sleep(0.015)

        report = {}
        with patch("mpsc2.main._bot_step", tick):
            assert await _play_realtime(session, list(range(4)), [], 120, report) == [Result.Tie] * 4
        assert report["play_wall_seconds"] > session.timeout
    asyncio.run(exercise())


def test_realtime_recovers_native_game_over_during_actions():
    async def tick(index, client, obs, iteration):
        client._status = Status.ended
        raise ProtocolError("['Game has already ended']")

    session = Session()
    with patch("mpsc2.main._bot_step", tick):
        assert asyncio.run(_play_realtime(session, list(range(4)), [], 120, {})) == [Result.Tie] * 4
    assert all(client.requests[-1] is None for client in session.clients)


@pytest.mark.parametrize("kind", ["policy", "protocol", "timeout"])
def test_realtime_failures_close_and_drain_all_clients(kind):
    async def exercise():
        session = Session()
        session.timeout = 0.02

        async def tick(index, *args):
            if index == 0:
                if kind == "policy":
                    raise ValueError("bad policy")
                if kind == "protocol":
                    raise ProtocolError("bad request")
            await asyncio.Event().wait()

        error = {"policy": ValueError, "protocol": ProtocolError, "timeout": TimeoutError}[kind]
        with patch("mpsc2.main._bot_step", tick), pytest.raises(error):
            await _play_realtime(session, list(range(4)), [], 120, {})
        for client in session.clients:
            client._ws.close.assert_awaited()
        assert len(asyncio.all_tasks()) == 1  # only this test coroutine remains
    asyncio.run(exercise())


def test_realtime_flag_and_team_metadata_reach_bot_startup():
    ai = SimpleNamespace(_initialize_variables=Mock(), _prepare_start=Mock(), _prepare_step=Mock(),
                         _prepare_first_step=Mock(), on_before_start=AsyncMock(), on_start=AsyncMock())
    client = SimpleNamespace(get_game_data=AsyncMock(), get_game_info=AsyncMock(),
                             ping=AsyncMock(return_value=api.Response(ping=api.ResponsePing(base_build=96883))),
                             _execute=AsyncMock())
    with patch("mpsc2.main.GameState"):
        asyncio.run(_initialize_bot(ai, client, 4, observation(4), 1, [7, 9, 7, 9], [1, 4, 2, 3], True))
    assert ai._prepare_start.call_args.kwargs["realtime"] is True
    assert ai.team_id == 9 and ai.ally_player_ids == (3,)
    ai.on_start.assert_awaited_once()


def test_native_realtime_session_rejects_manual_stepping(tmp_path):
    map_path = tmp_path / "map.SC2Map"
    map_path.write_bytes(b"fixture")
    session = NativeFourSession(map_path, output=tmp_path / "output", realtime=True)
    with pytest.raises(RuntimeError, match="advances automatically"):
        asyncio.run(session.step())
