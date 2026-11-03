"""Authenticated loopback WebSocket service. Remote exposure is not supported."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import time
from aiohttp import WSMsgType, web
from google.protobuf.message import DecodeError
from s2clientprotocol import sc2api_pb2 as api
from . import multiplayer_pb2 as pb
from .contract import MAX_FRAME, ServiceError, canonical, identifier, present, require
from .coordinator import Coordinator


class LocalServer:
    def __init__(self, factory, *, controller_token=None, port=0, **coordinator_options):
        self.controller_token = controller_token or secrets.token_hex(32)
        require(len(self.controller_token) >= 32 and self.controller_token.isascii(), 'Controller token needs at least 32 ASCII characters')
        require(type(port) is int and 0 <= port <= 65535, 'Invalid port')
        self.port = port
        self.coordinator = Coordinator(factory, **coordinator_options)
        self.app = web.Application(client_max_size=MAX_FRAME)
        self.app.router.add_get('/mpsc2/v1/control', self.control)
        self.app.router.add_get('/mpsc2/v1/matches/{match}/players/{slot}/{mode:sc2api|turns}', self.player)
        self.app.on_shutdown.append(self._shutdown)
        self.sockets, self.writers, self.control_records = set(), set(), {}
        self.runner = None
        self.url = None
        self.control_tasks = set()

    async def __aenter__(self):
        self.runner = web.AppRunner(self.app, shutdown_timeout=5, access_log=None)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, '127.0.0.1', self.port)
        try:
            await self.site.start()
        except BaseException:
            await self.runner.cleanup()
            raise
        self.port = self.site._server.sockets[0].getsockname()[1]
        self.url = f'http://127.0.0.1:{self.port}'
        return self

    async def __aexit__(self, *exc):
        if self.runner:
            await self.runner.cleanup()

    async def _shutdown(self, app):
        await self.coordinator.close()
        await asyncio.gather(*(ws.close(code=1001, message=b'Service shutdown') for ws in tuple(self.sockets)), return_exceptions=True)
        if self.control_tasks:
            await asyncio.gather(*self.control_tasks, return_exceptions=True)

    @staticmethod
    def _authorize(request, token):
        expected = 'Bearer ' + (token.decode('ascii') if isinstance(token, bytes) else token)
        if not hmac.compare_digest(request.headers.get('Authorization', '').encode(), expected.encode()):
            raise web.HTTPUnauthorized(text='Invalid credential')

    async def control(self, request):
        self._authorize(request, self.controller_token)
        negotiated = False

        async def dispatch(message):
            nonlocal negotiated
            present(message, 'request_id')
            identifier(message.request_id)
            op = message.WhichOneof('operation')
            require(op is not None, 'Unknown operation', pb.ERROR_UNSUPPORTED_MESSAGE)
            if op == 'hello':
                require(any(v.major == 1 and v.minor == 0 for v in message.hello.supported_versions), 'Protocol version 1.0 required', pb.ERROR_PROTOCOL_VERSION)
                negotiated = True
                return pb.ControlResponse(request_id=message.request_id, hello=pb.HelloResult(
                    selected_version=pb.ProtocolVersion(major=1, minor=0), server_revision='mpsc2-service-alpha1', maximum_frame_bytes=MAX_FRAME))
            require(negotiated, 'Hello negotiation required', pb.ERROR_PROTOCOL_VERSION)
            # Read-only calls are fresh snapshots. State-changing calls retain
            # outcomes (including errors) under a bounded idempotency key cache.
            if op in ('get_match', 'probe_match'):
                return await self._control_operation(message)
            digest = hashlib.sha256(canonical(message)).digest()
            record = self.control_records.get(message.request_id)
            if record:
                require(record[0] == digest, 'Request ID reused with different content', pb.ERROR_REQUEST_CONFLICT)
                return await asyncio.shield(record[1])
            require(len(self.control_records) < 2048, 'Control history exhausted; restart service', pb.ERROR_RESOURCE_LIMIT)
            task = asyncio.create_task(self._control_operation(message))
            self.control_records[message.request_id] = digest, task
            self.control_tasks.add(task)
            task.add_done_callback(self.control_tasks.discard)
            return await asyncio.shield(task)

        return await self._socket(request, pb.ControlRequest, pb.ControlResponse, dispatch)

    async def _control_operation(self, message):
        response = pb.ControlResponse(request_id=message.request_id)
        op = message.WhichOneof('operation')
        try:
            if op == 'prepare_match':
                result = await self.coordinator.prepare(message.prepare_match)
                match = self.coordinator.matches[result.match_id]
                mode = 'turns' if result.accepted_spec.transport == pb.TRANSPORT_JOINT_TURN else 'sc2api'
                for source, dest in zip(match.backend.bindings, result.players):
                    endpoint = f'{self.url}/mpsc2/v1/matches/{result.match_id}/players/{dest.slot_id}/{mode}'
                    source.endpoint = dest.endpoint = endpoint
                response.prepared_match.CopyFrom(result)
            elif op == 'probe_match':
                response.capabilities.CopyFrom(self.coordinator.factory.probe(message.probe_match))
            else:
                match = self.coordinator.get(getattr(message, op))
                if op == 'start_match':
                    snapshot = await match.start()
                elif op == 'close_match':
                    snapshot = await match.close()
                elif op == 'get_match':
                    snapshot = match.snapshot()
                else:
                    raise ServiceError(pb.ERROR_UNSUPPORTED_MESSAGE, 'Unsupported operation')
                response.match.CopyFrom(snapshot)
        except asyncio.CancelledError:
            response.error.CopyFrom(pb.Error(code=pb.ERROR_UNCERTAIN_EXECUTION, message='Operation cancelled during match cleanup'))
        except ServiceError as exc:
            response.error.CopyFrom(exc.proto)
        except Exception as exc:
            response.error.CopyFrom(pb.Error(code=pb.ERROR_ENGINE_API_UNAVAILABLE, message=f'{type(exc).__name__}: {exc}'))
        return response

    async def player(self, request):
        match = self.coordinator.matches.get(request.match_info['match'])
        slot, mode = request.match_info['slot'], request.match_info['mode']
        if match is None or slot not in match.tokens:
            raise web.HTTPNotFound()
        self._authorize(request, match.tokens[slot])
        if time.time() * 1000 >= match.expires:
            raise web.HTTPUnauthorized(text='Match lease expired')
        if match.state not in (pb.MATCH_RUNNING, pb.MATCH_ENDED):
            raise web.HTTPConflict(text='Match is not running')
        if (mode == 'turns') != (match.spec.transport == pb.TRANSPORT_JOINT_TURN):
            raise web.HTTPConflict(text='Wrong gameplay transport')
        key = match.id, slot
        if key in self.writers:
            raise web.HTTPConflict(text='This player already has a connection')
        self.writers.add(key)
        try:
            if mode == 'turns':
                async def dispatch(message):
                    present(message, 'request_id', 'match')
                    identifier(message.request_id)
                    match.verify_ref(message.match)
                    op = message.WhichOneof('operation')
                    response = pb.TurnResponse(request_id=message.request_id)
                    if op == 'submit':
                        response.accepted.CopyFrom(await match.submit(slot, message.submit))
                    elif op == 'await_turn':
                        present(message.await_turn, 'epoch')
                        response.result.CopyFrom(await match.await_turn(slot, message.await_turn.epoch))
                    elif op == 'read':
                        response.read.CopyFrom(await match.read(slot, message.read))
                    else:
                        raise ServiceError(pb.ERROR_UNSUPPORTED_MESSAGE, 'Unsupported turn operation')
                    return response
                return await self._socket(request, pb.TurnRequest, pb.TurnResponse, dispatch)
            else:
                async def dispatch(message):
                    result = await match.compat(slot, message)
                    if message.HasField('id'):
                        result.id = message.id
                    return result
                return await self._socket(request, api.Request, api.Response, dispatch, sc2=True)
        finally:
            self.writers.discard(key)
            if match.state in (pb.MATCH_RUNNING, pb.MATCH_STARTING):
                await match.fail(pb.ERROR_UNCERTAIN_EXECUTION, f'Player {slot} disconnected')

    async def _socket(self, request, request_type, response_type, dispatch, sc2=False):
        ws = web.WebSocketResponse(max_msg_size=MAX_FRAME, heartbeat=30)
        await ws.prepare(request)
        self.sockets.add(ws)
        pending = set()
        send_lock = asyncio.Lock()

        async def handle(data):
            message = request_type()
            try:
                message.ParseFromString(data)
                result = await dispatch(message)
                require(result.ByteSize() <= MAX_FRAME, 'Response exceeds negotiated limit', pb.ERROR_RESOURCE_LIMIT)
            except (DecodeError, ServiceError, ValueError) as exc:
                error = exc.proto if isinstance(exc, ServiceError) else pb.Error(code=pb.ERROR_INVALID_REQUEST, message=str(exc))
                if sc2:
                    result = api.Response(status=api.in_game, error=[f'{pb.ErrorCode.Name(error.code)}: {error.message}'])
                    if message.HasField('id'):
                        result.id = message.id
                else:
                    result = response_type(request_id=message.request_id, error=error)
            except Exception as exc:
                if sc2:
                    result = api.Response(status=api.in_game, error=[f'Engine transport failed: {type(exc).__name__}: {exc}'])
                    if message.HasField('id'):
                        result.id = message.id
                else:
                    result = response_type(request_id=message.request_id, error=pb.Error(code=pb.ERROR_UNCERTAIN_EXECUTION, message=str(exc)))
            async with send_lock:
                if not ws.closed:
                    await ws.send_bytes(result.SerializeToString())

        def completed(task):
            pending.discard(task)
            if not task.cancelled():
                task.exception()  # Observe transport errors; disconnect performs cleanup.

        try:
            async for frame in ws:
                if frame.type != WSMsgType.BINARY or len(pending) >= 8:
                    await ws.close(code=1008, message=b'Binary frames and at most 8 outstanding requests required')
                    break
                task = asyncio.create_task(handle(frame.data))
                pending.add(task)
                task.add_done_callback(completed)
        finally:
            self.sockets.discard(ws)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        return ws
