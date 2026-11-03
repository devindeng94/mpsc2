"""Wire-level and scheduling conformance; these tests do not certify an engine."""
import asyncio
from contextlib import AsyncExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from s2clientprotocol import sc2api_pb2 as api
from google.protobuf import text_format
from mpsc2 import maps
from mpsc2.service import (ControlClient, LocalServer, TurnClient, ServiceError,
                           match_spec, sc2_client, multiplayer_pb2 as pb)
from mpsc2.service.contract import copy, validate_spec


def spec(teams=(0, 0, 1, 1), **kwargs):
    return match_spec('engine', 'arena', maps.get('MPSC2TeamArena').path, teams, **kwargs)


class FakeBackend:
    def __init__(self, spec):
        self.spec = copy(spec)
        self.identity = pb.EngineIdentity(installation_id='engine', base_build=96883, api_ping_verified=True)
        self.bindings = [pb.PlayerBinding(slot_id=p.slot_id, team_id=p.team_id, transport=spec.transport, engine_instance_id=str(i), native_player_id=len(spec.players)-i)
                         for i, p in enumerate(spec.players)]
        self.materialized_map = copy(spec.map)
        self.loop = 7
        self.actions, self.advances, self.reads = [], [], []
        self.closed = self.partial = self.drift = self.bad_owner = self.terminal = False
        self.started = 0
        self.step_gate = None

    async def prepare(self):
        pass

    async def start(self):
        self.started += 1
        return await self.observe_all()

    async def request(self, slot, request):
        name = request.WhichOneof('request')
        self.reads.append((slot, name))
        response = api.Response(status=api.in_game)
        if request.HasField('id'):
            response.id = request.id
        if name == 'action':
            self.actions.append((slot, copy(request.action)))
            if self.partial and slot == 'p2':
                raise OSError('lost action acknowledgment')
            response.action.result.extend([1 for _ in request.action.actions])
            response.action.SetInParent()
        elif name == 'observation':
            binding = next(b for b in self.bindings if b.slot_id == slot)
            response.observation.observation.game_loop = self.loop + int(self.drift and slot == 'p2')
            response.observation.observation.player_common.player_id = 99 if self.bad_owner else binding.native_player_id
            if self.terminal:
                response.status = api.ended
                for b in self.bindings:
                    response.observation.player_result.add(player_id=b.native_player_id, result=api.Tie)
        elif name == 'ping':
            response.ping.base_build = 96883
        elif name == 'save_replay':
            response.save_replay.data = b'fake replay'
        else:
            getattr(response, name).SetInParent()
        return response

    async def advance_all(self, count):
        self.advances.append(count)
        if self.step_gate:
            await self.step_gate.wait()
        self.loop += count
        return [api.Response(step=api.ResponseStep(), status=api.in_game) for _ in self.bindings]

    async def observe_all(self):
        return [await self.request(b.slot_id, api.Request(observation=api.RequestObservation())) for b in self.bindings]

    async def close(self):
        self.closed = True
        if self.step_gate:
            self.step_gate.set()


class FakeFactory:
    def __init__(self):
        self.backends = []

    def probe(self, spec):
        validate_spec(spec)
        return pb.CapabilityReport(requested_spec=spec, maximum_agent_slots=32)

    def create(self, spec, match_id):
        self.backends.append(FakeBackend(spec))
        return self.backends[-1]


async def started(stack, specification=None, **options):
    factory = FakeFactory()
    server = await stack.enter_async_context(LocalServer(factory, **options))
    control = await stack.enter_async_context(ControlClient(server.url, server.controller_token))
    prepared = await control.prepare(specification or spec())
    snapshot = await control.start(prepared)
    return factory, server, control, prepared, snapshot


@pytest.mark.parametrize('teams', [(0,1), (7,7,7,-2), (0,0,1,1), (0,1,2,3), tuple(range(12))])
def test_joint_wire_no_early_dispatch_and_exactly_one_advance(teams):
    async def run():
        async with AsyncExitStack() as stack:
            factory, server, control, prepared, snapshot = await started(stack, spec(teams))
            clients = [await stack.enter_async_context(TurnClient(prepared, p.slot_id)) for p in prepared.players]
            backend = factory.backends[0]
            for c in clients[:-1]:
                accepted = await c.submit(0, snapshot.game_loop)
                assert accepted.epoch == 0
            assert backend.actions == [] and backend.advances == []
            await clients[-1].submit(0, snapshot.game_loop)
            results = await asyncio.gather(*(c.result(0) for c in clients))
            assert backend.advances == [8] and len(backend.actions) == len(teams)
            assert {r.game_loop for r in results} == {15}
            assert [r.observation.observation.player_common.player_id for r in results] == list(range(len(teams), 0, -1))
            await clients[0].submit(0, snapshot.game_loop)  # Semantically identical retry, including after completion.
            assert (await clients[0].result(0)) == results[0]
            assert backend.advances == [8]
            await control.close_match(prepared)
            assert backend.closed
    asyncio.run(run())


def test_conflicting_stale_and_missing_turns_rejected_without_dispatch():
    async def run():
        async with AsyncExitStack() as stack:
            factory, server, control, prepared, snapshot = await started(stack)
            client = await stack.enter_async_context(TurnClient(prepared, 'p1'))
            await client.submit(0, snapshot.game_loop)
            action = api.RequestAction(actions=[api.Action(action_chat=api.ActionChat(message='hello', channel=api.ActionChat.Broadcast))])
            for epoch, loop, actions in ((0, snapshot.game_loop, action), (1, snapshot.game_loop, None), (0, 999, None)):
                with pytest.raises(ServiceError) as caught:
                    await client.submit(epoch, loop, actions)
                assert caught.value.proto.code == pb.ERROR_ROUND_CONFLICT
            with pytest.raises(ServiceError):
                await client.call('submit', pb.SubmitTurn(epoch=0, expected_game_loop=snapshot.game_loop))
            client.match.generation = 'stale'
            with pytest.raises(ServiceError) as caught:
                await client.result(0)
            assert caught.value.proto.code == pb.ERROR_STALE_GENERATION
            assert factory.backends[0].actions == []
            await control.close_match(prepared)
    asyncio.run(run())


@pytest.mark.parametrize('failure,expected', [('partial', pb.ERROR_PARTIAL_DISPATCH), ('drift', pb.ERROR_UNCERTAIN_EXECUTION), ('bad_owner', pb.ERROR_ROSTER_MISMATCH)])
def test_round_failures_truncate_and_cleanup(failure, expected):
    async def run():
        async with AsyncExitStack() as stack:
            factory, server, control, prepared, snapshot = await started(stack)
            clients = [await stack.enter_async_context(TurnClient(prepared, p.slot_id)) for p in prepared.players]
            backend = factory.backends[0]
            setattr(backend, failure, True)
            for client in clients:
                await client.submit(0, snapshot.game_loop)
            for client in clients:
                with pytest.raises(ServiceError) as caught:
                    await client.result(0)
                assert caught.value.proto.code == expected
            state = await control.get(prepared)
            assert state.state == pb.MATCH_FAILED and state.truncated and not state.terminated and backend.closed
            assert backend.advances == ([] if failure == 'partial' else [8])
    asyncio.run(run())


def test_missing_player_deadline_aborts_whole_round():
    async def run():
        async with AsyncExitStack() as stack:
            factory, server, control, prepared, snapshot = await started(stack, spec(round_timeout_ms=100))
            client = await stack.enter_async_context(TurnClient(prepared, 'p1'))
            await client.submit(0, snapshot.game_loop)
            with pytest.raises(ServiceError) as caught:
                await client.result(0)
            assert caught.value.proto.code == pb.ERROR_ROUND_TIMEOUT
            assert factory.backends[0].closed and not factory.backends[0].actions
    asyncio.run(run())


def test_control_idempotency_and_conflict():
    async def run():
        async with AsyncExitStack() as stack:
            factory = FakeFactory()
            server = await stack.enter_async_context(LocalServer(factory))
            control = await stack.enter_async_context(ControlClient(server.url, server.controller_token))
            prepared = await control.prepare(spec(), request_id='allocate')
            assert await control.prepare(spec(), request_id='allocate') == prepared
            with pytest.raises(ServiceError) as caught:
                await control.prepare(spec((0,1)), request_id='allocate')
            assert caught.value.proto.code == pb.ERROR_REQUEST_CONFLICT
            snapshot = await control.start(prepared, request_id='start')
            assert await control.start(prepared, request_id='start') == snapshot
            assert factory.backends[0].started == 1 and len(factory.backends) == 1
            await control.close_match(prepared)
    asyncio.run(run())


def test_auth_mode_and_writer_isolation_and_disconnect():
    async def run():
        async with AsyncExitStack() as stack:
            factory, server, control, prepared, snapshot = await started(stack)
            with pytest.raises(aiohttp.WSServerHandshakeError):
                async with ControlClient(server.url, 'wrong-token'):
                    pass
            client = await stack.enter_async_context(TurnClient(prepared, 'p1'))
            with pytest.raises(aiohttp.WSServerHandshakeError):
                async with TurnClient(prepared, 'p1'):
                    pass
            # One player's token cannot authenticate another player's endpoint.
            p2 = TurnClient(prepared, 'p2')
            p2.token = client.token
            with pytest.raises(aiohttp.WSServerHandshakeError):
                async with p2:
                    pass
            await client.__aexit__()
            for _ in range(20):
                state = await control.get(prepared)
                if state.state == pb.MATCH_FAILED:
                    break
                await asyncio.sleep(0.01)
            assert state.state == pb.MATCH_FAILED and state.truncated and factory.backends[0].closed
    asyncio.run(run())


def test_joint_reads_do_not_leak_uncommitted_round():
    async def run():
        async with AsyncExitStack() as stack:
            factory, server, control, prepared, snapshot = await started(stack)
            clients = [await stack.enter_async_context(TurnClient(prepared, p.slot_id)) for p in prepared.players]
            backend = factory.backends[0]
            backend.step_gate = asyncio.Event()
            for client in clients:
                await client.submit(0, snapshot.game_loop)
            read = asyncio.create_task(clients[0].read(api.Request(observation=api.RequestObservation())))
            await asyncio.sleep(0.02)
            assert not read.done()
            backend.step_gate.set()
            assert (await read).observation.observation.game_loop == snapshot.game_loop + 8
            await control.close_match(prepared)
    asyncio.run(run())


def test_sc2_compat_actions_immediate_steps_barrier_and_admin_rejection():
    async def run():
        async with AsyncExitStack() as stack:
            factory, server, control, prepared, snapshot = await started(stack, spec(joint_turns=False))
            clients = [await stack.enter_async_context(sc2_client(prepared, p.slot_id, detect_layout=False)) for p in prepared.players]
            backend = factory.backends[0]
            await clients[0]._execute(action=api.RequestAction())
            assert len(backend.actions) == 1 and backend.advances == []
            votes = [asyncio.create_task(c.step(8)) for c in clients[:-1]]
            await asyncio.sleep(0.02)
            assert not backend.advances
            await clients[-1].step(8)
            await asyncio.gather(*votes)
            assert backend.advances == [8]
            response = await clients[0].observation()
            assert response.observation.observation.game_loop == 15
            from sc2.protocol import ProtocolError
            for name, value in [('debug', api.RequestDebug()), ('create_game', api.RequestCreateGame()),
                                ('observation', api.RequestObservation(disable_fog=True)), ('observation', api.RequestObservation(game_loop=999))]:
                with pytest.raises(ProtocolError):
                    await clients[0]._execute(**{name: value})
            assert (await clients[0]._execute(save_replay=api.RequestSaveReplay())).save_replay.data
            await control.close_match(prepared)
    asyncio.run(run())


def test_realtime_rejects_step_and_joint_mode():
    with pytest.raises(ServiceError):
        validate_spec(spec(realtime=True))
    async def run():
        async with AsyncExitStack() as stack:
            factory, server, control, prepared, snapshot = await started(stack, spec(realtime=True, joint_turns=False))
            assert not snapshot.HasField('game_loop')
            client = await stack.enter_async_context(sc2_client(prepared, 'p1', detect_layout=False))
            from sc2.protocol import ProtocolError
            with pytest.raises(ProtocolError):
                await client.step(8)
            await client.observation()
            await client._execute(action=api.RequestAction())
            assert not factory.backends[0].advances
            await control.close_match(prepared)
    asyncio.run(run())


def test_terminal_results_and_history_limit():
    async def run():
        async with AsyncExitStack() as stack:
            factory, server, control, prepared, snapshot = await started(stack, spec((0,1)))
            factory.backends[0].terminal = True
            clients = [await stack.enter_async_context(TurnClient(prepared, p.slot_id)) for p in prepared.players]
            for c in clients:
                await c.submit(0, snapshot.game_loop)
            results = await asyncio.gather(*(c.result(0) for c in clients))
            assert all(r.terminated and not r.truncated for r in results)
            state = await control.get(prepared)
            assert state.state == pb.MATCH_ENDED and len(state.player_results) == 2
            closed = await control.close_match(prepared)
            assert closed.terminated and not closed.truncated
    asyncio.run(run())


def test_protocol_examples_still_parse():
    for name, cls in [('prepare-2v2', pb.ControlRequest), ('submit-noop', pb.TurnRequest)]:
        message = text_format.Parse(Path(f'protocols/examples/{name}.textproto').read_text(), cls())
        assert cls.FromString(message.SerializeToString()) == message


def test_engine_stall_deadline_and_lease_close_release_waiters():
    async def run():
        async with AsyncExitStack() as stack:
            factory, server, control, prepared, snapshot = await started(stack, spec(round_timeout_ms=100))
            factory.backends[0].step_gate = asyncio.Event()
            clients = [await stack.enter_async_context(TurnClient(prepared, p.slot_id)) for p in prepared.players]
            for c in clients:
                await c.submit(0, snapshot.game_loop)
            with pytest.raises(ServiceError) as caught:
                await clients[0].result(0)
            assert caught.value.proto.code == pb.ERROR_ROUND_TIMEOUT
            assert factory.backends[0].closed
        async with AsyncExitStack() as stack:
            factory, server, control, prepared, snapshot = await started(stack, lease_seconds=0.1)
            await asyncio.sleep(0.15)
            assert (await control.get(prepared)).state == pb.MATCH_CLOSED and factory.backends[0].closed
    asyncio.run(run())


def test_prepare_is_not_running_and_wrong_transport_rejected():
    async def run():
        async with AsyncExitStack() as stack:
            factory = FakeFactory()
            server = await stack.enter_async_context(LocalServer(factory))
            control = await stack.enter_async_context(ControlClient(server.url, server.controller_token))
            prepared = await control.prepare(spec())
            assert (await control.get(prepared)).state == pb.MATCH_PREPARED and factory.backends[0].started == 0
            with pytest.raises(aiohttp.WSServerHandshakeError):
                async with TurnClient(prepared, 'p1'):
                    pass
            await control.start(prepared)
            client = TurnClient(prepared, 'p1')
            client.url = client.url.replace('/turns', '/sc2api')
            with pytest.raises(aiohttp.WSServerHandshakeError):
                async with client:
                    pass
            await control.close_match(prepared)
    asyncio.run(run())


def test_realtime_slow_observation_does_not_block_another_player_action():
    async def run():
        async with AsyncExitStack() as stack:
            factory, server, control, prepared, snapshot = await started(stack, spec(realtime=True, joint_turns=False))
            clients = [await stack.enter_async_context(sc2_client(prepared, p.slot_id, detect_layout=False)) for p in prepared.players]
            backend = factory.backends[0]
            gate = asyncio.Event()
            original = backend.request
            async def delayed(slot, request):
                if slot == 'p1' and request.WhichOneof('request') == 'observation':
                    await gate.wait()
                return await original(slot, request)
            backend.request = delayed
            observation = asyncio.create_task(clients[0].observation())
            await asyncio.wait_for(clients[1]._execute(action=api.RequestAction()), 0.5)
            assert not observation.done()
            gate.set()
            await observation
            await control.close_match(prepared)
    asyncio.run(run())


def test_bounded_history_fails_without_publishing_valid_round():
    async def run():
        async with AsyncExitStack() as stack:
            factory, server, control, prepared, snapshot = await started(stack, spec((0,1)), cache_bytes=40)
            clients = [await stack.enter_async_context(TurnClient(prepared, p.slot_id)) for p in prepared.players]
            for client in clients:
                await client.submit(0, snapshot.game_loop)
            with pytest.raises(ServiceError) as caught:
                await clients[0].result(0)
            assert caught.value.proto.code == pb.ERROR_RESOURCE_LIMIT
            assert (await control.get(prepared)).truncated
    asyncio.run(run())


def test_native_factory_refuses_mismatch_and_unsupported_requirements(tmp_path):
    from mpsc2.service.backend import NativeFactory, Installation
    from mpsc2.versions import MACOS_96883
    executable = MACOS_96883.executable(tmp_path)
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b'not the actual engine')
    factory = NativeFactory({'engine': Installation(tmp_path, '5.0.15.96883')},
                            {'arena': maps.get('MPSC2TeamArena').path}, tmp_path / 'runs')
    with patch('mpsc2.service.backend.platform.system', return_value='Darwin'):
        with pytest.raises(ServiceError) as caught:
            factory.probe(spec())
        assert caught.value.proto.code == pb.ERROR_ADAPTER_UNVERIFIED
        with patch('mpsc2.service.backend.file_sha256', return_value=MACOS_96883.executable_sha256):
            request = spec()
            request.engine.required_base_build = 98310
            with pytest.raises(ServiceError) as caught:
                factory.probe(request)
            assert caught.value.proto.code == pb.ERROR_ENGINE_IDENTITY_MISMATCH
            request = spec()
            request.required_capabilities.append('invented.v1')
            with pytest.raises(ServiceError) as caught:
                factory.create(request, 'match')
            assert caught.value.proto.code == pb.ERROR_CAPABILITY_UNAVAILABLE
            request = spec(realtime=True, joint_turns=False)
            request.required_capabilities.append('stepped-clock.v1')
            with pytest.raises(ServiceError):
                factory.create(request, 'match')
            request = spec()
            request.map.sha256 = b'0' * 32
            with pytest.raises(ServiceError):
                factory.probe(request)
    assert not (tmp_path / 'runs').exists()


def test_native_backend_raw_wire_does_not_translate_ability_ids(tmp_path):
    from mpsc2.service.backend import NativeBackend, Installation
    async def run():
        backend = NativeBackend(spec((0,1)), Installation(Path('.'), 'test'), Path('.'), tmp_path, pb.EngineIdentity(), 1)
        response = api.Response(action=api.ResponseAction(result=[1]), status=api.in_game)
        ws = SimpleNamespace(send_bytes=AsyncMock(), receive_bytes=AsyncMock(return_value=response.SerializeToString()))
        backend.session = SimpleNamespace(clients=[SimpleNamespace(_ws=ws)])
        command = api.Request(action=api.RequestAction())
        command.action.actions.add().action_raw.unit_command.ability_id = 4135
        assert await backend.request('p1', command) == response
        wire = api.Request.FromString(ws.send_bytes.call_args.args[0])
        assert wire.action.actions[0].action_raw.unit_command.ability_id == 4135
    asyncio.run(run())


def test_terminal_adjacent_frames_preserve_actual_observations():
    async def run():
        async with AsyncExitStack() as stack:
            factory, server, control, prepared, snapshot = await started(stack, spec((0,1)))
            backend = factory.backends[0]
            backend.terminal, backend.drift = True, True
            clients = [await stack.enter_async_context(TurnClient(prepared, p.slot_id)) for p in prepared.players]
            for c in clients:
                await c.submit(0, snapshot.game_loop)
            results = await asyncio.gather(*(c.result(0) for c in clients))
            assert [r.game_loop for r in results] == [15, 16]
            assert all(r.terminated and r.game_loop == r.observation.observation.game_loop for r in results)
            state = await control.get(prepared)
            assert state.terminated and not state.truncated and not state.HasField('game_loop')
            await control.close_match(prepared)
    asyncio.run(run())


def test_idle_control_connection_consumes_websocket_heartbeats():
    async def run():
        async with AsyncExitStack() as stack:
            factory, server, control, prepared, snapshot = await started(stack)
            # Server pings explicitly while the controller makes no RPC. The
            # control reader must consume it and reply with PONG while idle.
            controller_socket = next(iter(server.sockets))
            await controller_socket.ping(b'heartbeat-test')
            await asyncio.sleep(0.03)
            assert not control.reader.done()
            assert (await control.get(prepared)).state == pb.MATCH_RUNNING
            await control.close_match(prepared)
    asyncio.run(run())


def test_protocol_rejects_missing_semantics_and_bad_choices():
    changes = [lambda s: s.ClearField('teams'), lambda s: s.ClearField('random_seed'),
               lambda s: s.players[0].ClearField('team_id'), lambda s: s.players[0].ClearField('race'),
               lambda s: setattr(s.players[0], 'slot_id', '../p1'),
               lambda s: setattr(s, 'round_timeout_ms', 0), lambda s: setattr(s, 'step_count', 0),
               lambda s: setattr(s, 'game_time_limit_seconds', float('nan')),
               lambda s: setattr(s.players[1], 'slot_id', 'p1')]
    for change in changes:
        request = spec()
        change(request)
        with pytest.raises(ServiceError):
            validate_spec(request)


def test_failed_prepare_and_start_cleanup_and_own_generation():
    async def run():
        async with AsyncExitStack() as stack:
            factory = FakeFactory()
            server = await stack.enter_async_context(LocalServer(factory))
            control = await stack.enter_async_context(ControlClient(server.url, server.controller_token))
            original = factory.create
            def broken(spec, match_id):
                backend = original(spec, match_id)
                backend.prepare = AsyncMock(side_effect=OSError('prepare failed'))
                return backend
            factory.create = broken
            with pytest.raises(ServiceError):
                await control.prepare(spec())
            assert factory.backends[0].closed
            factory.create = original
            prepared = await control.prepare(spec())
            factory.backends[-1].bad_owner = True
            with pytest.raises(ServiceError):
                await control.start(prepared)
            assert factory.backends[-1].closed
            again = await control.prepare(spec())
            assert again.generation != prepared.generation
            assert again.match_id != prepared.match_id
            await control.close_match(again)
    asyncio.run(run())


def test_reserved_setup_commands_and_mutations_in_read_rejected():
    async def run():
        async with AsyncExitStack() as stack:
            factory, server, control, prepared, snapshot = await started(stack)
            client = await stack.enter_async_context(TurnClient(prepared, 'p1'))
            commands = api.RequestAction(actions=[api.Action(action_chat=api.ActionChat(message='MPSC2-SLOT-2'))])
            with pytest.raises(ServiceError):
                await client.submit(0, snapshot.game_loop, commands)
            for request in (api.Request(action=api.RequestAction()), api.Request(debug=api.RequestDebug()),
                            api.Request(observation=api.RequestObservation(disable_fog=True))):
                with pytest.raises(ServiceError):
                    await client.read(request)
            assert factory.backends[0].actions == []
            await control.close_match(prepared)
    asyncio.run(run())


def test_realtime_wrong_owner_fails_closed():
    async def run():
        async with AsyncExitStack() as stack:
            factory, server, control, prepared, snapshot = await started(stack, spec(realtime=True, joint_turns=False))
            client = await stack.enter_async_context(sc2_client(prepared, 'p1', detect_layout=False))
            factory.backends[0].bad_owner = True
            from sc2.protocol import ProtocolError
            with pytest.raises(ProtocolError):
                await client.observation()
            state = await control.get(prepared)
            assert state.state == pb.MATCH_FAILED and state.truncated
            assert factory.backends[0].closed
    asyncio.run(run())


def test_invalid_backend_bindings_rejected_before_publishing_prepared_match():
    async def run():
        async with AsyncExitStack() as stack:
            factory = FakeFactory()
            original = factory.create
            def duplicate(spec, match_id):
                backend = original(spec, match_id)
                backend.bindings[1].engine_instance_id = backend.bindings[0].engine_instance_id
                return backend
            factory.create = duplicate
            server = await stack.enter_async_context(LocalServer(factory))
            control = await stack.enter_async_context(ControlClient(server.url, server.controller_token))
            with pytest.raises(ServiceError) as caught:
                await control.prepare(spec())
            assert caught.value.proto.code == pb.ERROR_ROSTER_MISMATCH
            assert factory.backends[0].closed
    asyncio.run(run())


def test_unsupported_protocol_version_rejected_before_allocation():
    async def run():
        async with AsyncExitStack() as stack:
            factory = FakeFactory()
            server = await stack.enter_async_context(LocalServer(factory))
            async with aiohttp.ClientSession(headers={'Authorization': 'Bearer ' + server.controller_token}) as session:
                async with session.ws_connect(server.url + '/mpsc2/v1/control') as ws:
                    await ws.send_bytes(pb.ControlRequest(request_id='hello', hello=pb.Hello(
                        supported_versions=[pb.ProtocolVersion(major=2, minor=0)])).SerializeToString())
                    response = pb.ControlResponse.FromString(await ws.receive_bytes())
                    assert response.error.code == pb.ERROR_PROTOCOL_VERSION
                    await ws.send_bytes(pb.ControlRequest(request_id='prepare', prepare_match=spec()).SerializeToString())
                    response = pb.ControlResponse.FromString(await ws.receive_bytes())
                    assert response.error.code == pb.ERROR_PROTOCOL_VERSION
                    assert not factory.backends
    asyncio.run(run())


def test_terminal_frames_are_completion_metadata_not_a_decision_boundary():
    async def run():
        async with AsyncExitStack() as stack:
            factory, server, control, prepared, snapshot = await started(stack, spec(tuple(range(8))))
            backend = factory.backends[0]
            backend.terminal = True
            observe = backend.observe_all
            async def completed():
                observations = await observe()
                for i, response in enumerate(observations):
                    response.observation.observation.game_loop += i % 3
                return observations
            backend.observe_all = completed
            clients = [await stack.enter_async_context(TurnClient(prepared, p.slot_id)) for p in prepared.players]
            for c in clients:
                await c.submit(0, snapshot.game_loop)
            results = await asyncio.gather(*(c.result(0) for c in clients))
            assert [r.game_loop for r in results] == [15,16,17,15,16,17,15,16]
            assert all(r.terminated and not r.truncated for r in results)
            assert not (await control.get(prepared)).HasField('game_loop')
            await control.close_match(prepared)
    asyncio.run(run())


def test_terminal_results_without_all_native_ended_status_are_rejected():
    async def run():
        async with AsyncExitStack() as stack:
            factory, server, control, prepared, snapshot = await started(stack, spec((0,1)))
            backend = factory.backends[0]
            backend.terminal = True
            observe = backend.observe_all
            async def inconsistent():
                observations = await observe()
                observations[1].status = api.in_game
                return observations
            backend.observe_all = inconsistent
            clients = [await stack.enter_async_context(TurnClient(prepared, p.slot_id)) for p in prepared.players]
            for c in clients:
                await c.submit(0, snapshot.game_loop)
            with pytest.raises(ServiceError) as caught:
                await clients[0].result(0)
            assert caught.value.proto.code == pb.ERROR_UNCERTAIN_EXECUTION
            assert (await control.get(prepared)).truncated and backend.closed
    asyncio.run(run())


def test_lost_prepare_response_can_be_recovered_without_second_allocation():
    async def run():
        async with AsyncExitStack() as stack:
            factory = FakeFactory()
            gate = asyncio.Event()
            original = factory.create
            def delayed(spec, match_id):
                backend = original(spec, match_id)
                backend.prepare = gate.wait
                return backend
            factory.create = delayed
            server = await stack.enter_async_context(LocalServer(factory))
            first = await stack.enter_async_context(ControlClient(server.url, server.controller_token, timeout=0.1))
            with pytest.raises(asyncio.TimeoutError):
                await first.prepare(spec(), request_id='recover-prepare')
            second = await stack.enter_async_context(ControlClient(server.url, server.controller_token))
            retried = asyncio.create_task(second.prepare(spec(), request_id='recover-prepare'))
            await asyncio.sleep(0.02)
            assert len(factory.backends) == 1 and not retried.done()
            gate.set()
            prepared = await retried
            assert len(server.coordinator.matches) == 1
            await second.close_match(prepared)
    asyncio.run(run())


def test_cancelled_prepare_returns_a_retained_error_and_cleans_up():
    async def run():
        async with AsyncExitStack() as stack:
            factory = FakeFactory()
            original = factory.create
            def cancelled(spec, match_id):
                backend = original(spec, match_id)
                backend.prepare = AsyncMock(side_effect=asyncio.CancelledError())
                return backend
            factory.create = cancelled
            server = await stack.enter_async_context(LocalServer(factory))
            client = await stack.enter_async_context(ControlClient(server.url, server.controller_token, timeout=1))
            for _ in range(2):
                with pytest.raises(ServiceError) as caught:
                    await client.prepare(spec(), request_id='cancelled-prepare')
                assert caught.value.proto.code == pb.ERROR_UNCERTAIN_EXECUTION
            assert len(factory.backends) == 1 and factory.backends[0].closed
    asyncio.run(run())
