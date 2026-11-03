"""Headless Linux backend for the verified x86_64 SC2 4.10 executable."""
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
from types import SimpleNamespace

import psutil
from sc2.portconfig import Portconfig
from s2clientprotocol import sc2api_pb2 as api

from .installation import detect_installation, file_sha256
from .native_session import NativeProcess, RecordedClient, wait_record
from .versions import LINUX_75689, get_game_version, get_native_profile, require_registered_profile


class LinuxJoinTimeout(TimeoutError):
    """A native JoinGame barrier expired, before clients reached the caller."""


def _write_metadata(session):
    session.output.mkdir(parents=True, exist_ok=True)
    (session.output / 'native-session.json').write_text(
        json.dumps(session.native_metadata, indent=2) + '\n', encoding='utf-8')


def _join_engine_evidence(session):
    """Read only owned logs, after cleanup has flushed and closed them."""
    evidence = []
    for i in range(session.players):
        log = session.output / f'client-{i}' / 'engine.log'
        item = {'client_index': i, 'log_available': log.is_file(),
                'game_started': False, 'join_response_queued': False}
        if item['log_available']:
            with log.open(errors='replace') as stream:
                for line in stream:
                    item['game_started'] |= 'Game has started.' in line
                    item['join_response_queued'] |= 'Queuing response: join_game' in line
        evidence.append(item)
    return evidence


def _join_network_evidence(session):
    """Capture owned loopback socket states before the failed children exit.

    No extra API request is safe while JoinGame is pending. A passive snapshot
    distinguishes missing listeners/SYN_SENT sockets from native handshake
    stalls on established TCP connections, without interposing network traffic.
    """
    ports = set(session.native_metadata['server_ports'])
    ports.update(p for pair in session.native_metadata['guest_ports'] for p in pair)
    ports.update(p['api_port'] for p in session.native_metadata['processes'])
    records = []
    for i, (child, identity) in enumerate(zip(session.processes, session.native_metadata['processes'])):
        item = {'client_index': i, 'pid': identity['pid'], 'sockets': []}
        try:
            item['returncode'] = child._process.poll()
            if item['returncode'] is None:
                process = psutil.Process(identity['pid'])
                if process.create_time() != identity['process_create_time']:
                    raise RuntimeError('Owned process identity changed')
                connections = getattr(process, 'net_connections', None) or process.connections
                for connection in connections(kind='inet'):
                    local, remote = connection.laddr, connection.raddr
                    if (not local or local.ip not in ('127.0.0.1', '0.0.0.0')
                            or (remote and remote.ip != '127.0.0.1')
                            or not ({local.port} | ({remote.port} if remote else set())).intersection(ports)):
                        continue
                    item['sockets'].append({'fd': connection.fd, 'type': int(connection.type),
                                            'local': list(local), 'remote': list(remote),
                                            'status': connection.status})
        except (OSError, psutil.Error, RuntimeError) as exc:
            # Diagnostics must never prevent cleanup or disguise the timeout.
            item['error'] = f'{type(exc).__name__}: {exc}'
        records.append(item)
    return records


async def _join_players(session):
    clock = asyncio.get_running_loop()
    started = clock.time()
    progress = [{'client_index': i, 'state': 'pending'} for i in range(session.players)]
    session.native_metadata['join_progress'] = progress

    async def join(i, client):
        item = progress[i]
        item.update(state='requested', sent_seconds=clock.time() - started)
        try:
            player_id = await client.join_game(
                name=session.names[i], race=session.races[i],
                portconfig=session.ports if i == 0 else SimpleNamespace(
                    server=session.ports.server, players=[session.ports.players[i-1]]))
            item.update(state='joined', player_id=player_id)
            return player_id
        except BaseException as exc:
            item.update(state='interrupted', error=f'{type(exc).__name__}: {exc}')
            raise
        finally:
            item['elapsed_seconds'] = clock.time() - started

    try:
        return await session.call([join(i, client) for i, client in enumerate(session.clients)])
    except TimeoutError as exc:
        joined = sum(p['state'] == 'joined' for p in progress)
        raise LinuxJoinTimeout(
            f'Linux JoinGame timed out after {session.timeout}s '
            f'({joined}/{session.players} clients returned player IDs); '
            f'see {session.output / "native-session.json"} and client engine.log files'
        ) from exc


def compiler():
    return shutil.which(os.environ.get('MPSC2_LINUX_CC', 'gcc'))


def validate_executable(executable, profile=LINUX_75689):
    require_registered_profile(profile, 'linux-local-v1')
    if platform.system() != 'Linux' or platform.machine().lower() not in ('x86_64', 'amd64') or struct.calcsize('P') != 8:
        raise RuntimeError('Linux native multiplayer requires x86_64 Linux and 64-bit Python')
    if not executable.is_file() or file_sha256(executable) != profile.executable_sha256:
        raise RuntimeError(f'Unsupported Linux SC2 executable; requires verified Base{profile.build}')
    if not os.access(executable, os.X_OK):
        raise RuntimeError(f'SC2 executable is not executable: {executable}')


def build_bridge(output, profile=LINUX_75689):
    require_registered_profile(profile, 'linux-local-v1')
    cc = compiler()
    if not cc:
        raise RuntimeError('Linux 3–8 clients require GCC; install gcc or set MPSC2_LINUX_CC')
    source = Path(__file__).parent / profile.helper_sources[0]
    if file_sha256(source) != profile.helper_source_sha256[0]:
        raise RuntimeError('Linux helper source differs from the verified compatibility profile')
    target = output / 'linux_bridge.so'
    result = subprocess.run([cc, '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror',
                             str(source), '-o', str(target), '-ldl'],
                            capture_output=True, text=True, timeout=60)
    (output / 'bridge-build.log').write_text(result.stdout + result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError(f'Linux bridge compilation failed: {result.stderr}')
    header = target.read_bytes()[:20]
    if (len(header) != 20 or header[:6] != b'\x7fELF\x02\x01'
            or struct.unpack_from('<HH', header, 16) != (3, 62)):
        raise RuntimeError('Linux bridge compiler must produce an x86_64 ELF shared object')
    return target.resolve()


class LinuxProcess(NativeProcess):
    """LD_PRELOAD is scoped to this owned loopback child, never the parent."""

    def __init__(self, *args, helper=None, **kwargs):
        super().__init__(*args, **kwargs)
        # The official Linux binary is headless; no display server is required.
        for key in ('-displayMode', '-windowwidth', '-windowheight', '-windowx', '-windowy'):
            self._arguments.pop(key, None)
        self.env = dict(self.env)
        if helper:
            self.env.update(LD_PRELOAD=str(helper),
                            MPSC2_LINUX_GUARD_LOG=str(self.output / 'observation-guard.json'))

    async def _connect(self):
        if 'MPSC2_LINUX_GUARD_LOG' in self.env:
            guard = await wait_record(self.output, 'observation-guard.json', 10, self._process)
            if (not guard.get('applied') or guard.get('pid') != self._process.pid
                    or guard.get('profile_id') != LINUX_75689.id
                    or guard.get('host_player_count') != int(self.env.get('MPSC2_PLAYER_COUNT', '0'))):
                raise RuntimeError(f'Linux helper refused startup: {guard}')
            self.observation_guard = guard
        return await super()._connect()


async def enter_linux(session):
    # A partially connected native lobby can keep heartbeating indefinitely.
    # Recover only this pre-policy boundary, at most once. Never retry a game
    # after a JoinGame response, a native start marker, or any other failure.
    attempts = []
    previous_ports = set()
    for attempt in (1, 2):
        try:
            result = await _enter_linux_once(session, previous_ports)
        except LinuxJoinTimeout as exc:
            evidence = _join_engine_evidence(session)
            session.native_metadata['join_engine_evidence'] = evidence
            attempts.append({'attempt': attempt, 'outcome': 'join_timeout', 'error': str(exc),
                             'report': 'native-session.json'})
            session.native_metadata['startup_attempts'] = list(attempts)
            _write_metadata(session)
            progress = session.native_metadata.get('join_progress', [])
            retry = (attempt == 1 and session.players > 2
                     and len(progress) == session.players
                     and not any(p.get('state') == 'joined' for p in progress)
                     and all(e['log_available'] and not e['game_started']
                             and not e['join_response_queued'] for e in evidence))
            if not retry:
                raise
            previous_ports = set(session.native_metadata['server_ports'])
            previous_ports.update(p for pair in session.native_metadata['guest_ports'] for p in pair)
            archive = session.output / 'failed-join-attempt-1'
            archive.mkdir()  # Never overwrite earlier evidence.
            for path in [session.bridge_dir, *(session.output / f'client-{i}' for i in range(session.players)),
                         session.output / 'native-session.json']:
                path.rename(archive / path.name)
            attempts[-1]['report'] = 'failed-join-attempt-1/native-session.json'
            # _enter_linux_once has closed every owned child and released ports.
            session.stack = AsyncExitStack()
            session.clients, session.controllers, session.processes, session.player_ids = [], [], [], []
            print('Linux JoinGame stalled before any client joined; failed logs preserved in '
                  f'{archive}. Retrying once with new processes and ports.', flush=True)
        except BaseException as exc:
            attempts.append({'attempt': attempt, 'outcome': 'failed', 'error': f'{type(exc).__name__}: {exc}',
                             'report': 'native-session.json'})
            session.native_metadata['startup_attempts'] = attempts
            _write_metadata(session)
            raise
        else:
            attempts.append({'attempt': attempt, 'outcome': 'joined', 'report': 'native-session.json'})
            session.native_metadata['startup_attempts'] = attempts
            _write_metadata(session)
            return result


def _allocate_ports(players, excluded):
    rejected = []
    try:
        for _ in range(8):
            candidate = Portconfig(guests=players-1)
            values = set(candidate.server) | {p for pair in candidate.players for p in pair}
            if not values.intersection(excluded):
                return candidate
            # Keep conflicting allocations reserved while selecting another set.
            rejected.append(candidate)
        raise RuntimeError('Cannot allocate fresh Linux multiplayer ports for startup recovery')
    finally:
        for candidate in rejected:
            candidate.clean()


async def _enter_linux_once(session, excluded_ports=()):
    session.native_metadata = {'backend': 'linux', 'stage': 'validation'}
    try:
        profile = get_native_profile('Linux', session.sc2_version)
        if session.players not in profile.players:
            raise RuntimeError(f'{profile.id} does not support {session.players} players')
        if session.render_size or session.graphics_api:
            raise ValueError('The Linux native backend is headless; RGB rendering is not supported')
        version = get_game_version(profile.game_version, system='Linux')
        installation = ({'root': str(session.installation_root), 'platform': platform.system()}
                        if getattr(session, 'installation_root', None) is not None else detect_installation())
        if installation.get('platform') != 'Linux' or not installation.get('root'):
            raise RuntimeError('Cannot locate Linux SC2; set SC2PATH to the installation directory')
        root = Path(installation['root'])
        executable = profile.executable(root)
        validate_executable(executable, profile)
        session.bridge_dir.mkdir(parents=True)
        helper = build_bridge(session.bridge_dir, profile) if session.players > 2 else None
        session.ports = _allocate_ports(session.players, excluded_ports)
        session.native_metadata = {
            'stage': 'process_startup',
            'backend': 'linux', 'profile': profile.summary(), 'build': str(profile.build),
            'game_version': version.label, 'data_version': version.data_version,
            'executable': str(executable), 'executable_sha256': profile.executable_sha256,
            'helper_sha256': file_sha256(helper) if helper else None,
            'helper_source_sha256': file_sha256(Path(__file__).parent / profile.helper_sources[0]),
            'server_ports': session.ports.server, 'guest_ports': session.ports.players,
            'processes': [], 'realtime': session.realtime, 'player_count': session.players,
            'bridge_required': bool(helper), 'observation_guard_required': bool(helper),
        }
        env = {k: v for k, v in os.environ.items()
               if not k.startswith('MPSC2_') and k not in ('LD_PRELOAD', 'DYLD_INSERT_LIBRARIES')}
        for i in range(session.players):
            print(f'Starting independent Linux SC2 client {i+1}/{session.players}', flush=True)
            child_env = dict(env)
            if i == 0 and helper:
                child_env.update(MPSC2_PLAYER_COUNT=str(session.players),
                                 MPSC2_DISCOVERY_PORTS=','.join(str(p[0]) for p in session.ports.players))
            process = LinuxProcess(executable, root, session.output / f'client-{i}', child_env, i, helper=helper)
            process._arguments['-dataVersion'] = version.data_version
            session.processes.append(process)
            controller = await asyncio.wait_for(session.stack.enter_async_context(process), session.timeout)
            session.controllers.append(controller)
            ping = (await asyncio.wait_for(controller.ping(), session.timeout)).ping
            if ping.base_build != profile.build or ping.data_version.upper() != version.data_version:
                raise RuntimeError(f'Linux SC2 Ping does not match {profile.id}')
            client = RecordedClient(controller._ws, session.output / f'client-{i}/api.jsonl',
                                    detect_layout=profile.detect_ability_layout)
            if session.raw_affects_selection[i] is not None:
                client.raw_affects_selection = session.raw_affects_selection[i]
            session.clients.append(client)
            session.native_metadata['processes'].append({
                'pid': process._process.pid, 'api_port': process._port,
                'process_create_time': psutil.Process(process._process.pid).create_time(),
                'engine': {'game_version': ping.game_version, 'base_build': ping.base_build, 'data_version': ping.data_version},
                'observation_guard': getattr(process, 'observation_guard', None),
            })
        if getattr(session, 'prepared_hook', None) is not None:
            session.native_metadata['stage'] = 'prepared_hook'
            await session.prepared_hook(session)
        session.native_metadata['stage'] = 'create_game'
        request = api.RequestCreateGame(local_map=api.LocalMap(map_path=str(session.map_path)),
                                       realtime=session.realtime, random_seed=session.seed, disable_fog=session.disable_fog)
        for _ in range(session.players):
            request.player_setup.add(type=api.Participant)
        response = (await session.call([session.controllers[0]._execute(create_game=request)]))[0].create_game
        if response.HasField('error'):
            raise RuntimeError(f'Linux CreateGame failed: {response}')
        session.native_metadata['stage'] = 'join_game'
        session.player_ids = await _join_players(session)
        if set(session.player_ids) != set(range(1, session.players+1)):
            raise RuntimeError(f'Invalid native player IDs: {session.player_ids}')
        session.native_metadata['player_ids'] = session.player_ids
        session.native_metadata['readiness'] = {'native_ready_players': session.players, 'stock_api': not bool(helper)}
        session.native_metadata['stage'] = 'game_data'
        await session.call([client.get_game_data() for client in session.clients])
        session.native_metadata['ability_layouts'] = [client.ability_layout for client in session.clients]
        session.native_metadata['stage'] = 'ready'
        print(f'{session.players} Linux participants joined: {session.player_ids}', flush=True)
        return session
    except BaseException as exc:
        if isinstance(exc, LinuxJoinTimeout):
            session.native_metadata['join_network'] = _join_network_evidence(session)
        await session.close()
        raise
    finally:
        _write_metadata(session)
