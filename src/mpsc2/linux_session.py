"""Headless Linux backend for the verified x86_64 SC2 4.10 executable."""
from __future__ import annotations

import asyncio
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
    try:
        profile = get_native_profile('Linux', session.sc2_version)
        if session.players not in profile.players:
            raise RuntimeError(f'{profile.id} does not support {session.players} players')
        if session.render_size or session.graphics_api:
            raise ValueError('The Linux native backend is headless; RGB rendering is not supported')
        version = get_game_version(profile.game_version, system='Linux')
        installation = detect_installation()
        if installation.get('platform') != 'Linux' or not installation.get('root'):
            raise RuntimeError('Cannot locate Linux SC2; set SC2PATH to the installation directory')
        root = Path(installation['root'])
        executable = profile.executable(root)
        validate_executable(executable, profile)
        session.bridge_dir.mkdir(parents=True)
        helper = build_bridge(session.bridge_dir, profile) if session.players > 2 else None
        session.ports = Portconfig(guests=session.players-1)
        session.native_metadata = {
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
        request = api.RequestCreateGame(local_map=api.LocalMap(map_path=str(session.map_path)),
                                       realtime=session.realtime, random_seed=session.seed, disable_fog=session.disable_fog)
        for _ in range(session.players):
            request.player_setup.add(type=api.Participant)
        response = (await session.call([session.controllers[0]._execute(create_game=request)]))[0].create_game
        if response.HasField('error'):
            raise RuntimeError(f'Linux CreateGame failed: {response}')
        session.player_ids = await session.call([
            client.join_game(name=session.names[i], race=session.races[i],
                             portconfig=session.ports if i == 0 else SimpleNamespace(
                                 server=session.ports.server, players=[session.ports.players[i-1]]))
            for i, client in enumerate(session.clients)
        ])
        if set(session.player_ids) != set(range(1, session.players+1)):
            raise RuntimeError(f'Invalid native player IDs: {session.player_ids}')
        session.native_metadata['player_ids'] = session.player_ids
        session.native_metadata['readiness'] = {'native_ready_players': session.players, 'stock_api': not bool(helper)}
        await session.call([client.get_game_data() for client in session.clients])
        session.native_metadata['ability_layouts'] = [client.ability_layout for client in session.clients]
        print(f'{session.players} Linux participants joined: {session.player_ids}', flush=True)
        return session
    except BaseException:
        await session.close()
        raise
    finally:
        session.output.mkdir(parents=True, exist_ok=True)
        (session.output / 'native-session.json').write_text(json.dumps(session.native_metadata, indent=2)+'\n', encoding='utf-8')
