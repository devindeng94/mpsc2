"""Small async clients for the MPSC2 control and research transports."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import hashlib
from pathlib import Path
import uuid
from urllib.parse import urlsplit
import aiohttp
from s2clientprotocol import sc2api_pb2 as api
from . import multiplayer_pb2 as pb
from .contract import MAX_FRAME, ServiceError, require


def loopback_url(url):
    parsed = urlsplit(url)
    require(parsed.scheme in ('http', 'ws') and parsed.hostname in ('127.0.0.1', 'localhost', '::1')
            and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment,
            'Only local unencrypted service URLs are supported')
    return url


class WireClient:
    response_type = None

    def __init__(self, url, token, *, timeout=120):
        self.url = loopback_url(url)
        self.token = token.decode('ascii') if isinstance(token, bytes) else token
        self.timeout, self.session, self.ws = timeout, None, None
        self.lock = asyncio.Lock()
        self.inbox = asyncio.Queue(maxsize=8)
        self.reader = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers={'Authorization': 'Bearer ' + self.token})
        try:
            self.ws = await self.session.ws_connect(self.url, max_msg_size=MAX_FRAME, heartbeat=30)
            self.reader = asyncio.create_task(self._receive())
            return self
        except BaseException:
            await self.session.close()
            raise

    async def __aexit__(self, *exc):
        if self.session:
            await self.session.close()
        if self.reader:
            self.reader.cancel()
            await asyncio.gather(self.reader, return_exceptions=True)

    async def _receive(self):
        # Keep consuming WebSocket control frames even while the controller is
        # idle during gameplay; aiohttp handles heartbeat/pong in this reader.
        try:
            async for frame in self.ws:
                if frame.type != aiohttp.WSMsgType.BINARY:
                    raise ConnectionError('Unexpected service frame')
                self.inbox.put_nowait(self.response_type.FromString(frame.data))
            raise ConnectionError('Service connection closed')
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self.inbox.full():
                self.inbox.put_nowait(exc)

    async def exchange(self, request):
        async with self.lock:
            try:
                await self.ws.send_bytes(request.SerializeToString())
                response = await asyncio.wait_for(self.inbox.get(), self.timeout)
                if isinstance(response, Exception):
                    raise response
                require(response.request_id == request.request_id, 'Response ID mismatch', pb.ERROR_UNCERTAIN_EXECUTION)
            except BaseException:
                await self.session.close()  # A timed-out response cannot be reused as the next response.
                raise
            if response.HasField('error'):
                raise ServiceError(response.error.code, response.error.message,
                                   capability=response.error.capability, retry_safe=response.error.retry_safe)
            return response


class ControlClient(WireClient):
    response_type = pb.ControlResponse

    def __init__(self, url, token, **kwargs):
        super().__init__(url.rstrip('/') + '/mpsc2/v1/control', token, **kwargs)

    async def __aenter__(self):
        await super().__aenter__()
        try:
            response = await self.exchange(pb.ControlRequest(request_id=uuid.uuid4().hex,
                                hello=pb.Hello(supported_versions=[pb.ProtocolVersion(major=1, minor=0)])))
            require(response.HasField('hello') and response.hello.selected_version.major == 1
                    and response.hello.selected_version.minor == 0, 'Server did not select protocol 1.0', pb.ERROR_PROTOCOL_VERSION)
            return self
        except BaseException:
            await self.__aexit__()
            raise

    async def call(self, operation, value, *, request_id=None):
        return await self.exchange(pb.ControlRequest(request_id=request_id or uuid.uuid4().hex, **{operation: value}))

    async def prepare(self, spec, *, request_id=None):
        return (await self.call('prepare_match', spec, request_id=request_id)).prepared_match

    async def start(self, match, *, request_id=None):
        return (await self.call('start_match', reference(match), request_id=request_id)).match

    async def get(self, match):
        return (await self.call('get_match', reference(match))).match

    async def close_match(self, match, *, request_id=None):
        return (await self.call('close_match', reference(match), request_id=request_id)).match


def reference(match):
    if isinstance(match, pb.MatchRef):
        return match
    return pb.MatchRef(match_id=match.match_id, generation=match.generation)


def player_connection(prepared, slot):
    binding = next(p for p in prepared.players if p.slot_id == slot)
    credential = next(p for p in prepared.credentials if p.slot_id == slot)
    return binding.endpoint, credential.bearer_token


class TurnClient(WireClient):
    response_type = pb.TurnResponse

    def __init__(self, prepared, slot, **kwargs):
        url, token = player_connection(prepared, slot)
        super().__init__(url, token, **kwargs)
        self.match = reference(prepared)

    async def call(self, operation, value):
        return await self.exchange(pb.TurnRequest(request_id=uuid.uuid4().hex, match=self.match, **{operation: value}))

    async def submit(self, epoch, game_loop, actions=None):
        return (await self.call('submit', pb.SubmitTurn(epoch=epoch, expected_game_loop=game_loop,
                                      actions=api.RequestAction() if actions is None else actions))).accepted

    async def result(self, epoch):
        return (await self.call('await_turn', pb.AwaitTurn(epoch=epoch))).result

    async def read(self, request):
        return (await self.call('read', request)).read


@asynccontextmanager
async def sc2_client(prepared, slot, *, detect_layout=True):
    """Yield a ProfileClient carrying familiar python-sc2 gameplay methods.

    Game creation and joining already happened through ControlClient. The caller
    must close the match before disconnecting players, unless it has ended.
    """
    from ..protocol_compat import ProfileClient
    url, token = player_connection(prepared, slot)
    async with aiohttp.ClientSession(headers={'Authorization': 'Bearer ' + token.decode('ascii')}) as session:
        async with session.ws_connect(loopback_url(url), max_msg_size=MAX_FRAME, heartbeat=30) as ws:
            client = ProfileClient(ws, detect_layout=detect_layout)
            client.game_step = prepared.accepted_spec.step_count or 8
            await client.ping()
            yield client


def match_spec(installation_id, map_id, map_path, team_ids, *, races=None, realtime=False,
               joint_turns=True, random_seed=1, step_count=8, round_timeout_ms=60000, game_time_limit=120):
    """Build a complete spec for a registered bundled arena/melee source map."""
    from ..arena import validate_map
    source = Path(map_path)
    scenario = validate_map(source)
    teams = list(team_ids)
    races = [1] * len(teams) if races is None else list(races)
    require(len(races) == len(teams), 'One race per player required')
    spec = pb.MatchSpec(engine=pb.EngineSelection(installation_id=installation_id),
                map=pb.MapArtifact(artifact_id=map_id, sha256=hashlib.sha256(source.read_bytes()).digest(),
                                   rules_contract=f'mpsc2.{scenario}.fixed-teams.v1'),
                teams=pb.TeamRules(vision=pb.TEAM_VISION_SHARED, shared_unit_control=False, allied_victory=True),
                clock=pb.CLOCK_REALTIME if realtime else pb.CLOCK_STEPPED,
                transport=pb.TRANSPORT_JOINT_TURN if joint_turns else pb.TRANSPORT_SC2_COMPAT,
                random_seed=random_seed, step_count=step_count, round_timeout_ms=round_timeout_ms,
                game_time_limit_seconds=game_time_limit)
    for i, (team, race) in enumerate(zip(teams, races)):
        spec.players.add(slot_id=f'p{i+1}', team_id=team, race=getattr(race, 'value', race), kind=pb.PLAYER_AGENT,
                         interface_options=api.InterfaceOptions(raw=True, score=True, show_cloaked=True,
                              show_burrowed_shadows=True, show_placeholders=True, raw_affects_selection=False,
                              raw_crop_to_playable_area=False))
    return spec
