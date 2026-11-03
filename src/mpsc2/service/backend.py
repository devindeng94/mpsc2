"""Small backend boundary; native offsets never enter the public service API."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import platform
import time
from typing import Protocol
import uuid

from s2clientprotocol import sc2api_pb2 as api
from sc2.data import Race
from ..arena import prepare_map, validate_map
from ..installation import file_sha256
from ..native_session import NativeMultiplayerSession
from ..versions import get_native_profile
from . import multiplayer_pb2 as pb
from .contract import FEATURES, ServiceError, copy, require, validate_spec


class Backend(Protocol):
    """One object owns all clients of one match; request uses native wire IDs."""
    identity: pb.EngineIdentity
    bindings: list[pb.PlayerBinding]
    materialized_map: pb.MapArtifact

    async def prepare(self) -> None: ...
    async def start(self) -> list[api.Response]: ...
    async def request(self, slot: str, request: api.Request) -> api.Response: ...
    async def advance_all(self, count: int) -> list[api.Response]: ...
    async def observe_all(self) -> list[api.Response]: ...
    async def close(self) -> None: ...


@dataclass(frozen=True)
class Installation:
    root: Path
    version: str


class NativeFactory:
    """Explicit local registries, with no environment mutation or fallback engine."""
    def __init__(self, installations, maps, output, *, timeout=90):
        self.installations = dict(installations)
        self.maps = {k: Path(v).resolve() for k, v in maps.items()}
        self.output = Path(output).resolve()
        self.timeout = timeout

    def probe(self, spec):
        requested = validate_spec(spec)
        require(spec.engine.installation_id in self.installations, 'Unknown installation')
        require(spec.map.artifact_id in self.maps, 'Unknown registered map')
        installation = self.installations[spec.engine.installation_id]
        try:
            profile = get_native_profile(platform.system(), installation.version)
        except (ValueError, RuntimeError) as exc:
            raise ServiceError(pb.ERROR_ADAPTER_UNVERIFIED, str(exc)) from exc
        executable = profile.executable(Path(installation.root))
        require(executable.is_file(), 'Selected engine is missing', pb.ERROR_ENGINE_API_UNAVAILABLE)
        digest = file_sha256(executable)
        require(digest == profile.executable_sha256, 'Selected engine is not verified', pb.ERROR_ADAPTER_UNVERIFIED)
        require(not spec.engine.HasField('required_base_build') or spec.engine.required_base_build == profile.build,
                'Requested engine build differs from selected installation', pb.ERROR_ENGINE_IDENTITY_MISMATCH)
        require(not spec.engine.HasField('required_executable_sha256') or spec.engine.required_executable_sha256.hex() == digest,
                'Requested engine hash differs', pb.ERROR_ENGINE_IDENTITY_MISMATCH)
        path = self.maps[spec.map.artifact_id]
        require(path.is_file() and hashlib.sha256(path.read_bytes()).digest() == spec.map.sha256, 'Map hash mismatch')
        scenario = validate_map(path)
        require(spec.map.rules_contract == f'mpsc2.{scenario}.fixed-teams.v1', 'Unsupported map rules contract')
        require(len(spec.players) in profile.players and all(p.kind == pb.PLAYER_AGENT for p in spec.players),
                'This backend supports 2..8 agent slots only', pb.ERROR_CAPABILITY_UNAVAILABLE)
        require(len({p.team_id for p in spec.players}) >= 2, 'At least two opposing teams required')
        require(spec.teams.vision == pb.TEAM_VISION_SHARED and not spec.teams.shared_unit_control and spec.teams.allied_victory,
                'This map supports shared vision, no shared control, and allied victory', pb.ERROR_CAPABILITY_UNAVAILABLE)
        for p in spec.players:
            require(not p.interface_options.HasField('feature_layer') and not p.interface_options.HasField('render'),
                    'Only raw interfaces are supported', pb.ERROR_CAPABILITY_UNAVAILABLE)
        identity = pb.EngineIdentity(installation_id=spec.engine.installation_id, operating_system=profile.system,
                                     architecture=profile.architecture, base_build=profile.build,
                                     executable_sha256=bytes.fromhex(digest), adapter_id=profile.id,
                                     adapter_revision='service-native-v1', api_ping_verified=False)
        report = pb.CapabilityReport(engine=identity, requested_spec=spec,
                                     maximum_total_slots=max(profile.players), maximum_agent_slots=max(profile.players))
        supported_features = set(FEATURES)
        if spec.clock == pb.CLOCK_REALTIME:
            supported_features -= {'stepped-clock.v1', 'joint-turns.v1'}
        else:
            supported_features.discard('realtime-clock.v1')
        if spec.transport != pb.TRANSPORT_JOINT_TURN:
            supported_features.discard('joint-turns.v1')
        for feature in sorted(FEATURES | requested):
            supported = feature in supported_features
            report.capabilities.add(name=feature, state=pb.CAPABILITY_SUPPORTED if supported else pb.CAPABILITY_UNSUPPORTED,
                                    verification=pb.VERIFICATION_STATIC, reason='Static backend plan; gameplay not yet verified')
        return report

    def create(self, spec, match_id):
        report = self.probe(spec)
        for c in report.capabilities:
            if c.name in validate_spec(spec) and c.state != pb.CAPABILITY_SUPPORTED:
                raise ServiceError(pb.ERROR_CAPABILITY_UNAVAILABLE, 'Unsupported required feature', capability=c.name)
        return NativeBackend(spec, self.installations[spec.engine.installation_id], self.maps[spec.map.artifact_id],
                             self.output / match_id, report.engine, self.timeout)


class NativeBackend:
    def __init__(self, spec, installation, source, output, identity, timeout):
        self.spec, self.identity = copy(spec), copy(identity)
        self.installation, self.source, self.output = installation, source, output
        self.timeout = timeout
        self.session = None
        self.enter_task = None
        self.ready = asyncio.Event()
        self.start_gate = asyncio.Event()
        self.bindings = []
        self.materialized_map = pb.MapArtifact()
        self.locks = {p.slot_id: asyncio.Lock() for p in spec.players}
        self.close_lock = asyncio.Lock()
        self.closed = False

    async def _prepared(self, session):
        # Linux may invoke this again during pre-JoinGame recovery. Recheck
        # identity, refresh physical instance bindings and set interface options
        # on every replacement client. start_gate is already open on a retry.
        pings = await session.call([c.ping() for c in session.clients])
        first = pings[0].ping
        require(first.base_build == self.identity.base_build and bool(first.game_version) and bool(first.data_version),
                'Ping identity does not match selected engine', pb.ERROR_ENGINE_IDENTITY_MISMATCH)
        require(all(r.HasField('ping') and r.ping == first for r in pings),
                'Independent engines disagree on Ping identity', pb.ERROR_ENGINE_IDENTITY_MISMATCH)
        selected = self.spec.engine
        require(not selected.HasField('required_data_version') or first.data_version.upper() == selected.required_data_version.upper(),
                'Ping data version differs from requested version', pb.ERROR_ENGINE_IDENTITY_MISMATCH)
        self.identity.game_version, self.identity.data_version = first.game_version, first.data_version
        self.identity.api_ping_verified = True
        if session.native_metadata.get('helper_sha256'):
            self.identity.adapter_artifact_sha256 = bytes.fromhex(session.native_metadata['helper_sha256'])
        self.bindings = [pb.PlayerBinding(slot_id=p.slot_id, team_id=p.team_id, transport=self.spec.transport,
                                          engine_instance_id=f'{process._process.pid}-{uuid.uuid4().hex}')
                         for p, process in zip(self.spec.players, session.processes)]
        pids = [p._process.pid for p in session.processes]
        require(len(set(pids)) == len(self.spec.players), 'Engine processes are not independent', pb.ERROR_ROSTER_MISMATCH)
        for client, player in zip(session.clients, self.spec.players):
            client.join_options = copy(player.interface_options)
        self.ready.set()
        await self.start_gate.wait()

    async def prepare(self):
        self.output.mkdir(parents=True, exist_ok=False)
        spec = self.spec
        source_data = self.source.read_bytes()
        require(hashlib.sha256(source_data).digest() == spec.map.sha256, 'Map changed since registration')
        source_snapshot = self.output / 'source.SC2Map'
        source_snapshot.write_bytes(source_data)
        self.scenario = validate_map(source_snapshot)
        materialized = prepare_map(source_snapshot, self.output / 'game.SC2Map', [p.team_id for p in spec.players],
                                   spec.game_time_limit_seconds, realtime=spec.clock == pb.CLOCK_REALTIME)
        self.materialized_map.CopyFrom(pb.MapArtifact(artifact_id=self.output.name, sha256=hashlib.sha256(materialized.read_bytes()).digest(),
                                                      rules_contract=spec.map.rules_contract))
        self.session = NativeMultiplayerSession(materialized, output=self.output / 'session', players=len(spec.players),
                    races=[Race(p.race) for p in spec.players], names=[p.name or p.slot_id for p in spec.players],
                    seed=spec.random_seed, realtime=spec.clock == pb.CLOCK_REALTIME, timeout=self.timeout,
                    sc2_version=self.installation.version, installation_root=self.installation.root, prepared_hook=self._prepared)
        self.enter_task = asyncio.create_task(self.session.__aenter__())
        wait = asyncio.create_task(self.ready.wait())
        try:
            done, _ = await asyncio.wait({self.enter_task, wait}, timeout=self.timeout * len(spec.players), return_when=asyncio.FIRST_COMPLETED)
            if self.enter_task in done:
                await self.enter_task  # Propagate the startup failure.
                raise RuntimeError('Backend entered without a preparation boundary')
            require(wait in done, 'Engine preparation timed out', pb.ERROR_ENGINE_API_UNAVAILABLE)
        except BaseException:
            await self.close()
            raise
        finally:
            wait.cancel()
            await asyncio.gather(wait, return_exceptions=True)

    async def start(self):
        from ..main import _configure_teams
        self.start_gate.set()
        await self.enter_task
        observations, setup = await _configure_teams(self.session, [p.team_id for p in self.spec.players], self.scenario)
        for binding, pid in zip(self.bindings, self.session.player_ids):
            binding.native_player_id = pid
        # The realtime map freezes units until all players are ready.
        if self.session.realtime:
            await self.session.call([c.chat_send('MPSC2-READY', False) for c in self.session.clients])
            observations = await self.session.observe()
        (self.output / 'setup.json').write_text(json.dumps(setup, indent=2) + '\n', encoding='utf-8')
        return observations

    async def request(self, slot, request):
        index = next(i for i, p in enumerate(self.spec.players) if p.slot_id == slot)
        # Bypass ProfileClient translation here: the public service carries actual
        # catalog IDs. BotAI translation belongs to the policy-side client only.
        async with self.locks[slot]:
            ws = self.session.clients[index]._ws
            sent_ns = time.monotonic_ns()
            await ws.send_bytes(request.SerializeToString())
            data = await asyncio.wait_for(ws.receive_bytes(), self.timeout)
            response = api.Response.FromString(data)
            if self.output.is_dir():
                event = {'slot': slot, 'request': request.WhichOneof('request'), 'status': response.status,
                         'response_monotonic_ns': time.monotonic_ns(), 'sent_monotonic_ns': sent_ns, 'request_sha256': hashlib.sha256(request.SerializeToString()).hexdigest()}
                if response.HasField('observation'):
                    event.update(game_loop=response.observation.observation.game_loop,
                                 native_player_id=response.observation.observation.player_common.player_id,
                                 results={r.player_id: r.result for r in response.observation.player_result})
                if response.error:
                    event['errors'] = list(response.error)
                if response.HasField('action'):
                    event['action_results'] = list(response.action.result)
                with (self.output / 'service-wire.jsonl').open('a', encoding='utf-8') as journal:
                    journal.write(json.dumps(event) + '\n')
            return response

    async def advance_all(self, count):
        return await asyncio.gather(*(self.request(p.slot_id, api.Request(step=api.RequestStep(count=count))) for p in self.spec.players))

    async def observe_all(self):
        return await asyncio.gather(*(self.request(p.slot_id, api.Request(observation=api.RequestObservation())) for p in self.spec.players))

    async def close(self):
        async with self.close_lock:
            if self.closed:
                return
            self.closed = True
            # Close transports before cancelling upstream Protocol requests, whose
            # cancellation handler otherwise waits for a missing engine response.
            if self.session:
                for process in self.session.processes:
                    if process._session is not None:
                        await process._session.close()
            if self.enter_task and not self.enter_task.done():
                self.enter_task.cancel()
            if self.enter_task:
                await asyncio.gather(self.enter_task, return_exceptions=True)
            if self.session:
                await self.session.close()
