"""Build-pinned Windows local multiplayer backend; imported only on Windows."""
from __future__ import annotations

import asyncio
import ctypes as c
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sysconfig
from types import SimpleNamespace
import psutil

from sc2.portconfig import Portconfig
from s2clientprotocol import sc2api_pb2 as api

from .installation import detect_installation, file_sha256
from .native_session import NativeProcess, RecordedClient, wait_record
from .versions import (WINDOWS_93333, get_native_profile, get_game_version,
                       require_registered_profile, write_windows_header)

# Compatibility aliases for existing integrations; the registry owns these values.
BUILD = str(WINDOWS_93333.build)
EXECUTABLE_SHA256 = WINDOWS_93333.executable_sha256


def compiler():
    """Use an explicitly selected MinGW-w64 GCC, or one on PATH."""
    explicit = os.environ.get('MPSC2_WINDOWS_CC')
    return shutil.which(explicit) if explicit else shutil.which('gcc')


def validate_executable(executable, profile=WINDOWS_93333):
    require_registered_profile(profile, 'windows-local-v1')
    if not executable.is_file() or file_sha256(executable) != profile.executable_sha256:
        raise RuntimeError(f'Unsupported Windows SC2 executable; requires verified Base{profile.build}')
    if c.sizeof(c.c_void_p) != 8:
        raise RuntimeError('Windows multiplayer requires 64-bit Python')
    if sysconfig.get_platform().lower() != 'win-amd64':
        raise RuntimeError('The Windows x86_64 profile requires an x86_64 Windows Python interpreter')


def build_bridge(output, profile=WINDOWS_93333):
    header = write_windows_header(output, profile)
    cc = compiler()
    if not cc:
        raise RuntimeError('Windows 3–8 clients require MinGW-w64 gcc; set MPSC2_WINDOWS_CC to gcc.exe')
    source = Path(__file__).parent / profile.helper_sources[0]
    minhook = source.parent / 'minhook/src'
    target = output / 'windows_bridge.dll'
    result = subprocess.run([cc, '-shared', '-O2', '-Wall', '-Wextra', '-static-libgcc', '-I', str(header.parent.resolve()),
                             str(source), *[str(minhook / name) for name in ('buffer.c', 'hook.c', 'trampoline.c', 'hde/hde64.c')],
                             '-o', str(target), '-lws2_32', '-lshell32'],
                            capture_output=True, text=True, timeout=60,
                            env={**os.environ, 'PATH': str(Path(cc).resolve().parent) + os.pathsep + os.environ.get('PATH', '')})
    (output / 'bridge-build.log').write_text(result.stdout + result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError(f'Windows bridge compilation failed: {result.stderr}')
    data = target.read_bytes()
    pe = struct.unpack_from('<I', data, 0x3c)[0] if len(data) >= 64 else len(data)
    if (data[:2] != b'MZ' or pe+24 > len(data) or data[pe:pe+4] != b'PE\0\0'
            or struct.unpack_from('<H', data, pe+4)[0] != 0x8664
            or not struct.unpack_from('<H', data, pe+22)[0] & 0x2000):
        raise RuntimeError('Windows bridge compiler must produce a Windows x86_64 DLL; use MinGW-w64 GCC')
    return target.resolve()


def load_bridge(process, library):
    """Load a helper into this launcher's own child using its Popen handle.

    Never enumerate unrelated processes or open a caller-provided PID. No
    debug privileges, persistent system settings, or installed-file changes.
    """
    if c.sizeof(c.c_void_p) != 8:
        raise RuntimeError('Windows multiplayer requires 64-bit Python')
    k = c.WinDLL('kernel32', use_last_error=True)
    k.VirtualAllocEx.argtypes = [c.c_void_p, c.c_void_p, c.c_size_t, c.c_ulong, c.c_ulong]
    k.VirtualAllocEx.restype = c.c_void_p
    k.VirtualFreeEx.argtypes = [c.c_void_p, c.c_void_p, c.c_size_t, c.c_ulong]
    k.WriteProcessMemory.argtypes = [c.c_void_p, c.c_void_p, c.c_void_p, c.c_size_t, c.c_void_p]
    k.GetModuleHandleW.argtypes = [c.c_wchar_p]
    k.GetModuleHandleW.restype = c.c_void_p
    k.GetProcAddress.argtypes = [c.c_void_p, c.c_char_p]
    k.GetProcAddress.restype = c.c_void_p
    k.GetModuleHandleExW.argtypes = [c.c_ulong, c.c_void_p, c.c_void_p]
    k.GetModuleFileNameW.argtypes = [c.c_void_p, c.c_wchar_p, c.c_ulong]
    k.CreateRemoteThread.argtypes = [c.c_void_p, c.c_void_p, c.c_size_t, c.c_void_p, c.c_void_p, c.c_ulong, c.c_void_p]
    k.CreateRemoteThread.restype = c.c_void_p
    k.WaitForSingleObject.argtypes = [c.c_void_p, c.c_ulong]
    k.CloseHandle.argtypes = [c.c_void_p]
    handle = int(process._handle)
    path = (str(library.resolve()) + '\0').encode('utf-16-le')
    address = k.VirtualAllocEx(handle, None, len(path), 0x3000, 4)
    if not address:
        raise c.WinError(c.get_last_error())
    thread = None
    finished = False
    try:
        written = c.c_size_t()
        if not k.WriteProcessMemory(handle, address, path, len(path), c.byref(written)) or written.value != len(path):
            raise c.WinError(c.get_last_error())
        loader = k.GetProcAddress(k.GetModuleHandleW('kernel32.dll'), b'LoadLibraryW')
        # Resolve the owner (including forwarded exports), then use the child's
        # module base. Do not assume identical system-DLL addresses under ASLR.
        owner = c.c_void_p()
        if not loader or not k.GetModuleHandleExW(6, loader, c.byref(owner)):
            raise c.WinError(c.get_last_error())
        filename = c.create_unicode_buffer(32768)
        if not k.GetModuleFileNameW(owner, filename, len(filename)):
            raise c.WinError(c.get_last_error())
        owner_name = Path(filename.value).name.casefold()
        ps = c.WinDLL('psapi', use_last_error=True)
        ps.EnumProcessModules.argtypes = [c.c_void_p, c.c_void_p, c.c_ulong, c.c_void_p]
        ps.GetModuleFileNameExW.argtypes = [c.c_void_p, c.c_void_p, c.c_wchar_p, c.c_ulong]
        modules = (c.c_void_p * 1024)()
        needed = c.c_ulong()
        if not ps.EnumProcessModules(handle, modules, c.sizeof(modules), c.byref(needed)) or needed.value > c.sizeof(modules):
            raise RuntimeError('Cannot enumerate owned SC2 modules for the bridge loader')
        for remote_base in modules[:needed.value // c.sizeof(c.c_void_p)]:
            if ps.GetModuleFileNameExW(handle, remote_base, filename, len(filename)) and Path(filename.value).name.casefold() == owner_name:
                loader = remote_base + loader - owner.value
                break
        else:
            raise RuntimeError('Bridge loader module is absent from owned SC2 process')
        thread = k.CreateRemoteThread(handle, None, 0, loader, address, 0, None)
        if not thread:
            raise c.WinError(c.get_last_error())
        if k.WaitForSingleObject(thread, 10000) != 0:
            raise RuntimeError('Windows bridge loader timed out; closing owned process')
        finished = True
    finally:
        if thread:
            k.CloseHandle(thread)
        # A timed-out loader may still read the path. Process cleanup reclaims it.
        if finished or not thread:
            k.VirtualFreeEx(handle, address, 0, 0x8000)


class WindowsProcess(NativeProcess):
    def __init__(self, *args, helper=None, bridge_dir=None, profile=WINDOWS_93333, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper, self.bridge_dir = helper, bridge_dir
        self.profile = profile

    def _launch(self):
        self.output.mkdir(parents=True, exist_ok=True)
        command = [str(self.executable), '-listen', '127.0.0.1', '-port', str(self._port),
                   '-dataDir', str(self.root), '-tempDir', self._tmp_dir, '-verbose']
        for key, value in self._arguments.items():
            command.extend([key, value])
        (self.output / 'launch.json').write_text(json.dumps(command, indent=2)+'\n', encoding='utf-8')
        self.log = (self.output / 'engine.log').open('wb')
        return subprocess.Popen(command, cwd=self.root / self.profile.working_directory, env=self.env,
                                stdout=self.log, stderr=subprocess.STDOUT)

    async def _connect(self):
        ws = await super()._connect()
        # Code has unpacked by the time the API accepts a connection.
        self._ws = ws  # also close it if helper startup fails
        if self.helper:
            load_bridge(self._process, self.helper)
            if 'MPSC2_WINDOWS_GUARD_LOG' in self.env:
                guarded = await wait_record(self.output, 'observation-guard.json', 10, self._process)
                if (not guarded.get('applied') or guarded.get('pid') != self._process.pid
                        or guarded.get('profile_id') != self.profile.id):
                    raise RuntimeError(f'Windows observation guard refused startup: {guarded}')
                self.observation_guard = guarded
            if 'MPSC2_BRIDGE_DIR' not in self.env:
                return ws
            loaded = await wait_record(self.bridge_dir, 'bridge-loaded.json', 10, self._process)
            if (not loaded.get('loaded') or loaded.get('pid') != self._process.pid
                    or loaded.get('profile_id') != self.profile.id):
                raise RuntimeError('Windows bridge report does not match the owned process')
        return ws


def configure_data_version(process, profile, data_version):
    """Base98370 crashes on offline chat with an explicit -dataVersion.

    Its installed content is usable only after the API confirms the expected
    build and data identifier. Older profiles retain their launch arguments.
    """
    if profile.data_selection == 'installed-verified':
        process._arguments.pop('-dataVersion', None)
    elif profile.data_selection == 'explicit':
        if data_version:
            process._arguments['-dataVersion'] = data_version
    else:
        raise RuntimeError(f'Unsupported data selection strategy: {profile.data_selection}')


async def verify_installed_data(controller, profile, data_version, timeout):
    ping = (await asyncio.wait_for(controller.ping(), timeout)).ping
    engine = {'game_version': ping.game_version, 'base_build': ping.base_build,
              'data_version': ping.data_version}
    if ping.base_build != profile.build or (profile.data_selection == 'installed-verified' and
                                           ping.data_version.upper() != data_version.upper()):
        raise RuntimeError(f'Installed SC2 data does not match Base{profile.build}/{data_version}: {engine}. '
                           'This profile cannot force historical data with -dataVersion.')
    return engine


async def enter_windows(session):
    """Platform-isolated counterpart of the proven macOS session handshake."""
    host_task = None
    try:
        profile = get_native_profile('Windows', session.sc2_version)
        if session.players not in profile.players:
            raise RuntimeError(f'{profile.id} does not support {session.players} players')
        version = get_game_version(session.sc2_version if session.sc2_version is not None else profile.game_version, system='Windows')
        installation = detect_installation()
        if not installation.get('root') or installation.get('platform', 'Windows') != 'Windows':
            raise RuntimeError('Cannot locate a Windows SC2 installation for the selected profile')
        root = Path(installation['root'])
        executable = profile.executable(root)
        validate_executable(executable, profile)
        if not (root / profile.working_directory).is_dir():
            raise RuntimeError('Windows multiplayer requires the installation Support64 directory')
        session.bridge_dir.mkdir(parents=True)
        helper = build_bridge(session.bridge_dir, profile) if session.players > 2 else None
        session.ports = Portconfig(guests=session.players-1)
        session.native_metadata = {
            'backend': 'windows', 'build': str(profile.build), 'executable': str(executable),
            'profile': profile.summary(), 'game_version': version.label, 'data_version': version.data_version,
            'executable_sha256': profile.executable_sha256,
            'helper_sha256': file_sha256(helper) if helper else None,
            'helper_source_sha256': file_sha256(Path(__file__).parent / 'native/windows_bridge.c'),
            'profile_header_sha256': file_sha256(session.bridge_dir / 'mpsc2_windows_profile.h') if helper else None,
            'server_ports': session.ports.server, 'guest_ports': session.ports.players,
            'processes': [], 'realtime': session.realtime, 'player_count': session.players,
            'bridge_required': bool(helper), 'observation_guard_required': bool(helper),
        }
        env = {k: v for k, v in os.environ.items() if not k.startswith('MPSC2_') and k != 'DYLD_INSERT_LIBRARIES'}
        for i in range(session.players):
            print(f'Starting independent Windows SC2 client {i+1}/{session.players}', flush=True)
            host_env = {**env, 'MPSC2_BRIDGE_DIR': str(session.bridge_dir),
                        'MPSC2_PLAYER_COUNT': str(session.players),
                        'MPSC2_DISCOVERY_PORTS': ','.join(str(p[0]) for p in session.ports.players)} if i == 0 and helper else dict(env)
            if helper:
                host_env['MPSC2_WINDOWS_GUARD_LOG'] = str(session.output / f'client-{i}' / 'observation-guard.json')
            process = WindowsProcess(executable, root, session.output / f'client-{i}', host_env, i,
                                     resolution=session.window_size or session.render_size or (640,480),
                                     graphics_api=session.graphics_api, helper=helper,
                                     bridge_dir=session.bridge_dir, profile=profile)
            configure_data_version(process, profile, version.data_version)
            session.processes.append(process)
            controller = await asyncio.wait_for(session.stack.enter_async_context(process), session.timeout)
            session.controllers.append(controller)
            engine = await verify_installed_data(controller, profile, version.data_version, session.timeout)
            client = RecordedClient(controller._ws, session.output / f'client-{i}/api.jsonl',
                                    render_size=session.render_size, detect_layout=profile.detect_ability_layout)
            if session.raw_affects_selection[i] is not None:
                client.raw_affects_selection = session.raw_affects_selection[i]
            session.clients.append(client)
            session.native_metadata['processes'].append({'pid': process._process.pid, 'api_port': process._port,
                **({'engine': engine} if engine is not None else {}),
                'process_create_time': psutil.Process(process._process.pid).create_time(),
                'observation_guard': getattr(process, 'observation_guard', None)})
        request = api.RequestCreateGame(local_map=api.LocalMap(map_path=str(session.map_path)),
                                        realtime=session.realtime, random_seed=session.seed, disable_fog=session.disable_fog)
        for _ in range(session.players):
            request.player_setup.add(type=api.Participant)
        response = (await session.call([session.controllers[0]._execute(create_game=request)]))[0]
        error = response.create_game
        session.native_metadata['stock_create_error'] = {'code': error.error if error.HasField('error') else None,
                                                        'details': error.error_details}
        if session.players > 2:
            if not error.HasField('error') or error.error != api.ResponseCreateGame.InvalidPlayerSetup or error.error_details != 'Only 1v1 is supported when using multiple agents':
                raise RuntimeError('Unexpected CreateGame response; refusing Windows state transition')
            (session.bridge_dir / 'promote.signal').write_text('response-complete\n', encoding='utf-8')
            session.native_metadata['promotion'] = await wait_record(session.bridge_dir, 'promote.json', 10, session.processes[0]._process)
            if not session.native_metadata['promotion'].get('promoted'):
                raise RuntimeError('Windows host promotion failed')
            ping = (await session.call([session.clients[0].ping()]))[0]
            if ping.status != api.init_game:
                raise RuntimeError('Windows host did not enter init_game')
            host_task = asyncio.create_task(session.clients[0].join_game(name=session.names[0], race=session.races[0], portconfig=session.ports))
            await wait_record(session.bridge_dir, 'held.json', 20, session.processes[0]._process)
            async def host_result():
                return await host_task
            session.player_ids = await session.call([host_result(), *[
                client.join_game(name=session.names[i], race=session.races[i],
                                 portconfig=SimpleNamespace(server=session.ports.server, players=[session.ports.players[i-1]]))
                for i, client in enumerate(session.clients) if i]])
            session.native_metadata['readiness'] = await wait_record(session.bridge_dir, 'players-ready.json', 5)
        else:
            if error.HasField('error'):
                raise RuntimeError(f'CreateGame failed: {error}')
            session.player_ids = await session.call([client.join_game(name=session.names[i], race=session.races[i], portconfig=session.ports)
                                                     for i, client in enumerate(session.clients)])
            session.native_metadata['readiness'] = {'native_ready_players': 2, 'stock_api': True}
        if set(session.player_ids) != set(range(1, session.players+1)):
            raise RuntimeError(f'Invalid player IDs: {session.player_ids}')
        session.native_metadata['player_ids'] = session.player_ids
        # The launch hash may be echoed by Ping while newer content is loaded.
        # Inspect real game metadata before any policy or setup actions run.
        await session.call([client.get_game_data() for client in session.clients])
        session.native_metadata['ability_layouts'] = [client.ability_layout for client in session.clients]
        print(f'{session.players} Windows participants joined: {session.player_ids}', flush=True)
        return session
    except BaseException:
        await session.close()
        if host_task is not None:
            host_task.cancel()
            await asyncio.gather(host_task, return_exceptions=True)
        raise
    finally:
        session.output.mkdir(parents=True, exist_ok=True)
        (session.output / 'native-session.json').write_text(json.dumps(session.native_metadata, indent=2)+'\n', encoding='utf-8')
