"""Linux backend refusal, ownership, join and replay boundaries."""
import asyncio
from dataclasses import replace
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from s2clientprotocol import sc2api_pb2 as api

from mpsc2.linux_session import LinuxProcess, build_bridge, validate_executable
from mpsc2.native_session import NativeMultiplayerSession
from mpsc2.versions import LINUX_75689, UnsupportedNativeProfile, get_game_version


def test_linux_doctor_warns_about_uppercase_only_maps_without_modifying_them(tmp_path, monkeypatch):
    from mpsc2.installation import detect_installation
    monkeypatch.setenv('SC2PATH', str(tmp_path))
    (tmp_path/'Maps/Ladder').mkdir(parents=True)
    (tmp_path/'maps/SMAC_Maps').mkdir(parents=True)
    if (tmp_path/'maps/Ladder').exists():
        pytest.skip('Map-directory case test requires a case-sensitive filesystem')
    with patch('mpsc2.installation.upstream.platform_detect', return_value='Linux'):
        report = detect_installation()
    assert any('lowercase maps/' in warning and 'Ladder' in warning for warning in report['warnings'])
    assert not (tmp_path/'maps/Ladder').exists()
    assert (tmp_path/'maps/SMAC_Maps').is_dir()


@pytest.mark.parametrize('problem', [None, 'compiler', 'architecture', 'permission'])
def test_linux_doctor_reports_platform_prerequisites(problem, tmp_path):
    from mpsc2.capabilities import get_capabilities
    executable = LINUX_75689.executable(tmp_path)
    executable.parent.mkdir(parents=True)
    executable.touch()
    installation = {'platform':'Linux', 'root':str(tmp_path), 'ready':True,
                    'checks':{}, 'errors':[], 'installed_builds':[75689]}
    with patch('mpsc2.capabilities.detect_installation', return_value=installation), \
         patch('mpsc2.capabilities.platform.system', return_value='Linux'), \
         patch('mpsc2.capabilities.platform.machine', return_value='aarch64' if problem == 'architecture' else 'x86_64'), \
         patch('mpsc2.capabilities.file_sha256', return_value=LINUX_75689.executable_sha256), \
         patch('mpsc2.linux_session.compiler', return_value=None if problem == 'compiler' else '/usr/bin/gcc'), \
         patch('os.access', return_value=problem != 'permission'):
        report = get_capabilities()['multiplayer']
    assert report['backend'] == 'linux-local-v1'
    assert report['ready'] == (problem is None)
    assert 'clang' not in report['checks'] and 'windows_compiler' not in report['checks']
    assert bool(report['errors']) == (problem is not None)


@pytest.mark.parametrize('system,machine,bits', [('Darwin','x86_64',8), ('Linux','aarch64',8), ('Linux','x86_64',4)])
def test_linux_rejects_foreign_runtime_before_binary_access(system, machine, bits, tmp_path):
    with patch('mpsc2.linux_session.platform.system', return_value=system), \
         patch('mpsc2.linux_session.platform.machine', return_value=machine), \
         patch('mpsc2.linux_session.struct.calcsize', return_value=bits), \
         patch('mpsc2.linux_session.file_sha256') as digest:
        with pytest.raises(RuntimeError, match='x86_64 Linux'):
            validate_executable(tmp_path/'SC2_x64')
    digest.assert_not_called()


def test_linux_rejects_modified_binary(tmp_path):
    executable = tmp_path/'SC2_x64'
    executable.write_bytes(b'unknown')
    with patch('mpsc2.linux_session.platform.system', return_value='Linux'), \
         patch('mpsc2.linux_session.platform.machine', return_value='x86_64'):
        with pytest.raises(RuntimeError, match='Unsupported Linux SC2'):
            validate_executable(executable)


def test_linux_helper_profile_and_source_are_bound(tmp_path):
    with patch('mpsc2.linux_session.subprocess.run') as compile_helper:
        with pytest.raises(UnsupportedNativeProfile):
            build_bridge(tmp_path, replace(LINUX_75689, executable_sha256='0'*64))
        with patch('mpsc2.linux_session.compiler', return_value='gcc'), \
             patch('mpsc2.linux_session.file_sha256', return_value='0'*64):
            with pytest.raises(RuntimeError, match='helper source differs'):
                build_bridge(tmp_path)
    compile_helper.assert_not_called()


@pytest.mark.parametrize('guard', [
    {'applied': False}, {'applied': True, 'pid': 999},
    {'applied': True, 'pid': 17, 'profile_id': 'foreign', 'host_player_count': 4},
    {'applied': True, 'pid': 17, 'profile_id': LINUX_75689.id, 'host_player_count': 3},
])
def test_linux_report_refusal_precedes_socket_connection(guard, tmp_path):
    process = LinuxProcess.__new__(LinuxProcess)
    process.output = tmp_path
    process.env = {'MPSC2_LINUX_GUARD_LOG': 'guard.json', 'MPSC2_PLAYER_COUNT': '4'}
    process._process = SimpleNamespace(pid=17)
    with patch('mpsc2.linux_session.wait_record', new_callable=AsyncMock, return_value=guard), \
         patch('mpsc2.native_session.NativeProcess._connect', new_callable=AsyncMock) as connect:
        with pytest.raises(RuntimeError, match='refused startup'):
            asyncio.run(process._connect())
    connect.assert_not_awaited()


@pytest.mark.parametrize('count', [2, 4, 8])
@pytest.mark.parametrize('failure', [None, 'ping', 'join'])
def test_linux_join_uses_distinct_ports_and_cleans_all_children(count, failure, tmp_path, monkeypatch):
    source = tmp_path/'map.SC2Map'
    source.touch()
    session = NativeMultiplayerSession(source, output=tmp_path/'run', players=count, realtime=True)
    processes, clients = [], []
    monkeypatch.setenv('LD_PRELOAD', 'parent-library')
    monkeypatch.setenv('MPSC2_PLAYER_COUNT', '99')
    def process(*args, **kwargs):
        index = len(processes)
        child = AsyncMock()
        child._process = SimpleNamespace(pid=100+index)
        child._port = 5000+index
        child._arguments = {}
        child.observation_guard = None
        controller = child.__aenter__.return_value
        controller._execute.return_value = api.Response(create_game=api.ResponseCreateGame())
        controller.ping.return_value = api.Response(ping=api.ResponsePing(
            base_build=123 if failure == 'ping' else 75689,
            data_version=get_game_version(75689).data_version))
        assert 'LD_PRELOAD' not in args[3]
        assert args[3].get('MPSC2_PLAYER_COUNT') == (str(count) if index == 0 and count > 2 else None)
        assert bool(kwargs['helper']) == (count > 2)
        processes.append(child)
        return child
    def client(*args, **kwargs):
        child = AsyncMock()
        child.join_game.return_value = len(clients)+1
        child.ability_layout = 'legacy-4.10-3800'
        if failure == 'join' and not clients:
            child.join_game.side_effect = RuntimeError('test join failure')
        clients.append(child)
        return child
    async def run():
        async with session:
            assert session.player_ids == list(range(1,count+1))
    with patch('mpsc2.native_session.platform.system', return_value='Linux'), \
         patch('mpsc2.linux_session.detect_installation', return_value={'platform':'Linux', 'root':str(tmp_path)}), \
         patch('mpsc2.linux_session.validate_executable'), \
         patch('mpsc2.linux_session.build_bridge', return_value=tmp_path/'bridge.so') as build, \
         patch('mpsc2.linux_session.file_sha256', return_value='fixture'), \
         patch('mpsc2.linux_session.psutil.Process', return_value=SimpleNamespace(create_time=lambda: 123.0)), \
         patch('mpsc2.linux_session.LinuxProcess', side_effect=process), \
         patch('mpsc2.linux_session.RecordedClient', side_effect=client):
        if failure:
            with pytest.raises(RuntimeError, match='Ping|join failure'):
                asyncio.run(run())
        else:
            asyncio.run(run())
    assert build.call_count == int(count > 2)
    assert all(p.__aexit__.await_count == 1 for p in processes)
    assert os.environ['LD_PRELOAD'] == 'parent-library'
    if not failure:
        ports = [c.join_game.call_args.kwargs['portconfig'] for c in clients]
        assert len(ports[0].players) == count-1
        assert [p.players[0] for p in ports[1:]] == ports[0].players
        assert all(c.get_game_data.await_count == 1 for c in clients)
        report = json.loads((session.output/'native-session.json').read_text())
        assert report['realtime'] and report['ability_layouts'] == ['legacy-4.10-3800']*count


@pytest.mark.parametrize('observed', [0, 3, 4, 8])
def test_linux_replay_uses_exact_engine_and_guards_high_ids(observed, tmp_path):
    from mpsc2.replay import run_replay
    replay = tmp_path/'game.SC2Replay'
    replay.touch()
    process = AsyncMock()
    process._arguments = {}
    process.__aenter__.return_value._execute.return_value = api.Response(
        start_replay=api.ResponseStartReplay(), status=api.in_replay)
    data = get_game_version(75689).data_version
    with patch('mpsc2.replay.get_replay_version', return_value=('Base75689', data)), \
         patch('mpsc2.replay.platform.system', return_value='Linux'), \
         patch('mpsc2.installation.detect_installation', return_value={'root': str(tmp_path)}), \
         patch('mpsc2.linux_session.validate_executable'), \
         patch('mpsc2.linux_session.build_bridge', return_value=tmp_path/'guard.so') as build, \
         patch('mpsc2.linux_session.LinuxProcess', return_value=process) as launch, \
         patch('mpsc2.replay.OwnedSC2Process') as stock, \
         patch('mpsc2.protocol_compat.ProfileClient', return_value=AsyncMock()), \
         patch('mpsc2.replay._play', new_callable=AsyncMock, return_value={}):
        assert run_replay(None, replay, observed_id=observed) == {}
    stock.assert_not_called()
    assert build.call_count == int(observed >= 4)
    assert 'MPSC2_PLAYER_COUNT' not in launch.call_args.args[3]
    assert process._arguments['-dataVersion'] == data
    request = process.__aenter__.return_value._execute.call_args.kwargs['start_replay']
    assert request.HasField('replay_data') and not request.HasField('replay_path')
    assert request.observed_player_id == observed
    process.__aexit__.assert_awaited_once()


@pytest.mark.skipif(platform.system() != 'Linux' or platform.machine() != 'x86_64' or not shutil.which('gcc'),
                    reason='Native helper rejection requires Linux x86_64 and GCC')
def test_compiled_linux_helper_refuses_unrelated_executable(tmp_path):
    helper = build_bridge(tmp_path)
    report = tmp_path/'guard.json'
    result = subprocess.run(['/bin/true', '-listen', '127.0.0.1'], env={
        **os.environ, 'LD_PRELOAD':str(helper), 'MPSC2_LINUX_GUARD_LOG':str(report)}, timeout=10)
    assert result.returncode == 96
    assert json.loads(report.read_text())['error'] == 'unexpected executable build ID'
