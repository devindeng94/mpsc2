"""Wire-level invariants, without SC2 or any python-sc2 imports in the harness."""
import asyncio
import importlib.util
from pathlib import Path
import sys
from unittest.mock import AsyncMock, Mock

import pytest
from s2clientprotocol import sc2api_pb2 as api

spec = importlib.util.spec_from_file_location("raw_probe", Path(__file__).resolve().parents[1] / "scripts/probe_raw_protocol.py")
raw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(raw)


def test_create_preserves_four_participants_and_omitted_realtime(tmp_path):
    request = raw.create_request(tmp_path / "map.SC2Map", [api.Participant] * 4, None)
    request = api.RequestCreateGame.FromString(request.SerializeToString())
    assert [p.type for p in request.player_setup] == [api.Participant] * 4
    assert not request.HasField("realtime")


def test_join_sends_every_guest_port_pair():
    ports = {"server": [5000, 5001], "clients": [[5002, 5003], [5004, 5005], [5006, 5007]]}
    request = raw.join_request(3, ports)
    assert request.HasField("race")
    assert not request.HasField("observed_player_id")
    assert [(p.game_port, p.base_port) for p in request.client_ports] == [tuple(p) for p in ports["clients"]]
    assert request.host_ip == "127.0.0.1"


def test_response_error_presence_not_default_value():
    response = api.Response(create_game=api.ResponseCreateGame())
    # Proto2 defaults error to enum's first value, even when field is absent.
    assert response.create_game.error == api.ResponseCreateGame.MissingMap
    assert raw.accepted(response, "create_game")
    response.create_game.error = api.ResponseCreateGame.InvalidPlayerSetup
    assert not raw.accepted(response, "create_game")
    assert not raw.accepted(api.Response(error=["invalid request"]), "create_game")


def test_summary_removes_binary_without_mutating_wire_message():
    request = api.Request(create_game=api.RequestCreateGame(local_map=api.LocalMap(map_data=b"map bytes")))
    before = request.SerializeToString()
    summary = raw.compact_message(request)
    assert request.SerializeToString() == before
    assert "map_data" not in summary["create_game"]["local_map"]
    assert summary["binary_fields"]["create_game.local_map.map_data"]["bytes"] == 9


def fake_client(tmp_path):
    client = object.__new__(raw.RawClient)
    client.output = tmp_path
    client.request_id = 0
    client.timeout = 0.02
    client.lock = asyncio.Lock()
    client.ws = AsyncMock()
    return client


def test_transport_timeout_closes_stream(tmp_path):
    async def exercise():
        client = fake_client(tmp_path)

        async def never():
            await asyncio.Event().wait()

        client.ws.receive_bytes.side_effect = never
        with pytest.raises(TimeoutError):
            await client.call("ping", api.RequestPing())
        client.ws.close.assert_awaited_once()
        request = api.Request.FromString((tmp_path / "001-ping.request.pb").read_bytes())
        assert request.id == 1 and request.HasField("ping")
    asyncio.run(exercise())


def test_transport_rejects_mismatched_response_id(tmp_path):
    async def exercise():
        client = fake_client(tmp_path)
        client.ws.receive_bytes.return_value = api.Response(id=99, ping=api.ResponsePing()).SerializeToString()
        with pytest.raises(RuntimeError, match="Mismatched response id"):
            await client.call("ping", api.RequestPing())
        client.ws.close.assert_awaited_once()
    asyncio.run(exercise())


def test_partial_join_preserves_timeout_and_inspects_only_joined_clients(tmp_path):
    async def exercise():
        clients = [Mock(call=AsyncMock()) for _ in range(4)]
        roster = api.Response(game_info=api.ResponseGameInfo(player_info=[
            api.PlayerInfo(player_id=i, type=api.Participant) for i in [1, 2]]))
        for i in range(2):
            clients[i].call.side_effect = [api.Response(join_game=api.ResponseJoinGame(player_id=i+1)), roster]
        for i in [2, 3]:
            clients[i].call.side_effect = TimeoutError()
        network = {"server": [5000, 5001], "clients": [[5002, 5003], [5004, 5005], [5006, 5007]]}
        result = await raw.join_attempt(clients, Mock(network=lambda _: network), tmp_path, 1,
                                        guest_ports="per-guest")
        assert result["verified_independent_participants"] == 0
        assert result["join_responses"][2] == {"transport_error": "TimeoutError: "}
        assert [r["client"] for r in result["partial_rosters"]] == [0, 1]
        # Each guest must receive its own bind ports in this experiment; the
        # timed-out guests must never be queried again on their closed streams.
        for i in range(1, 4):
            join = clients[i].call.call_args_list[0].args[1]
            assert [(p.game_port, p.base_port) for p in join.client_ports] == [tuple(network["clients"][i-1])]
        assert clients[2].call.await_count == clients[3].call.await_count == 1
    asyncio.run(exercise())
