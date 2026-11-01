"""Windows backend boundaries, runnable without Windows or SC2."""
import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from mpsc2.native_session import NativeMultiplayerSession
from mpsc2.windows_session import (BUILD, EXECUTABLE_SHA256, WindowsProcess,
                                   build_bridge, compiler, validate_executable,
                                   configure_data_version, verify_installed_data)
from mpsc2.versions import WINDOWS_93333, WINDOWS_98370, get_game_version


@pytest.mark.parametrize('contents', [None, b'unrecognized executable'])
def test_unknown_windows_build_never_authorizes_helper(contents, tmp_path):
    executable = tmp_path / 'SC2_x64.exe'
    if contents is not None:
        executable.write_bytes(contents)
    with pytest.raises(RuntimeError, match='Unsupported Windows SC2 executable'):
        validate_executable(executable)


def test_windows_requires_64_bit_python(tmp_path):
    executable = tmp_path / 'SC2_x64.exe'
    executable.touch()
    with patch('mpsc2.windows_session.file_sha256', return_value=EXECUTABLE_SHA256), \
         patch('mpsc2.windows_session.c.sizeof', return_value=4):
        with pytest.raises(RuntimeError, match='64-bit Python'):
            validate_executable(executable)


def test_explicit_compiler_does_not_fall_back(monkeypatch):
    monkeypatch.setenv('MPSC2_WINDOWS_CC', 'missing-gcc')
    with patch('mpsc2.windows_session.shutil.which', return_value=None) as which:
        assert compiler() is None
    which.assert_called_once_with('missing-gcc')


def test_compile_failure_records_diagnostic(tmp_path):
    with patch('mpsc2.windows_session.compiler', return_value=str(tmp_path / 'toolchain/gcc.exe')), \
         patch('mpsc2.windows_session.subprocess.run', return_value=SimpleNamespace(returncode=1, stdout='', stderr='bad target')) as run:
        with pytest.raises(RuntimeError, match='bad target'):
            build_bridge(tmp_path)
    assert 'bad target' in (tmp_path / 'bridge-build.log').read_text(encoding='utf-8')
    assert run.call_args.kwargs['env']['PATH'].split(os.pathsep)[0] == str(tmp_path / 'toolchain')
    assert any(x.endswith('hde64.c') for x in run.call_args.args[0])


def test_windows_launch_uses_support64_and_child_environment(tmp_path):
    process = WindowsProcess(tmp_path / 'SC2_x64.exe', tmp_path, tmp_path / 'output', {'CHILD': 'only'}, 0)
    before = dict(os.environ)
    try:
        with patch('mpsc2.windows_session.subprocess.Popen') as launch:
            process._launch()
        assert launch.call_args.kwargs['cwd'] == tmp_path / 'Support64'
        assert launch.call_args.kwargs['env'] == {'CHILD': 'only'}
        command = launch.call_args.args[0]
        assert command[1:3] == ['-listen', '127.0.0.1']
        assert '-run' not in command
        assert dict(os.environ) == before
    finally:
        process._clean()


def test_bad_windows_build_refused_before_launch_or_compile(tmp_path):
    source = tmp_path / 'map.SC2Map'
    source.write_bytes(b'map')
    session = NativeMultiplayerSession(source, output=tmp_path / 'run')
    with patch('mpsc2.native_session.platform.system', return_value='Windows'), \
         patch('mpsc2.windows_session.detect_installation', return_value={'ready': True, 'root': str(tmp_path)}), \
         patch('mpsc2.windows_session.build_bridge') as build, \
         patch('mpsc2.windows_session.WindowsProcess') as launch:
        with pytest.raises(RuntimeError, match='Unsupported Windows SC2 executable'):
            asyncio.run(session.__aenter__())
    build.assert_not_called()
    launch.assert_not_called()


def test_helper_report_must_belong_to_owned_process(tmp_path):
    process = WindowsProcess.__new__(WindowsProcess)
    process.helper = tmp_path / 'bridge.dll'
    process.bridge_dir = tmp_path
    process._process = SimpleNamespace(pid=17)
    process.env = {'MPSC2_BRIDGE_DIR': str(tmp_path)}
    ws = object()
    with patch('mpsc2.native_session.NativeProcess._connect', new_callable=AsyncMock, return_value=ws), \
         patch('mpsc2.windows_session.load_bridge'), \
         patch('mpsc2.windows_session.wait_record', new_callable=AsyncMock, return_value={'loaded': True, 'pid': 16}):
        with pytest.raises(RuntimeError, match='owned process'):
            asyncio.run(process._connect())
    assert process._ws is ws  # failure cleanup can close the connected socket


@pytest.mark.parametrize('default_installation_ready', [True, False])
@pytest.mark.parametrize('target_build', [75689, 93333, 98370])
def test_two_player_windows_session_needs_no_native_helper(tmp_path, default_installation_ready, target_build):
    # A missing unrelated latest build must not block the selected profile.
    (tmp_path/'Support64').mkdir()
    source = tmp_path / 'map.SC2Map'
    source.write_bytes(b'map')
    session = NativeMultiplayerSession(source, output=tmp_path / 'run', players=2, sc2_version=target_build)
    from s2clientprotocol import sc2api_pb2 as api
    response = api.Response(create_game=api.ResponseCreateGame())
    processes = []
    def process(*args, **kwargs):
        obj = AsyncMock()
        obj._process = SimpleNamespace(pid=100+len(processes))
        obj._port = 5000+len(processes)
        obj.observation_guard = None
        obj._arguments = {}
        obj.__aenter__.return_value._execute.return_value = response
        obj.__aenter__.return_value.ping.return_value = api.Response(ping=api.ResponsePing(
            base_build=target_build, data_version=get_game_version(target_build).data_version))
        (session.output / f'client-{len(processes)}').mkdir()
        processes.append(obj)
        assert kwargs['helper'] is None
        return obj
    clients = []
    def client(*args, **kwargs):
        obj = AsyncMock()
        obj.join_game.return_value = len(clients)+1
        obj.ability_layout = 'test-layout'
        clients.append(obj)
        return obj
    async def run():
        async with session:
            assert session.player_ids == [1,2]
    with patch('mpsc2.native_session.platform.system', return_value='Windows'), \
         patch('mpsc2.windows_session.detect_installation', return_value={'ready': default_installation_ready, 'root': str(tmp_path)}), \
         patch('mpsc2.windows_session.validate_executable'), \
         patch('mpsc2.windows_session.psutil.Process', return_value=SimpleNamespace(create_time=lambda: 123.0)), \
         patch('mpsc2.windows_session.build_bridge') as build, \
         patch('mpsc2.windows_session.WindowsProcess', side_effect=process), \
         patch('mpsc2.windows_session.RecordedClient', side_effect=client):
        asyncio.run(run())
    build.assert_not_called()
    assert all(p.__aexit__.await_count == 1 for p in processes)
    report = json.loads((session.output / 'native-session.json').read_text(encoding='utf-8'))
    assert report['readiness']['stock_api'] and not report['bridge_required']
    assert all(('-dataVersion' in p._arguments) == (target_build != 98370) for p in processes)
    assert all(p['engine']['base_build'] == target_build for p in report['processes'])
    assert report['ability_layouts'] == ['test-layout']*2
    assert all(c.get_game_data.await_count == 1 for c in clients)


def test_macos_dispatch_does_not_import_windows_backend(tmp_path):
    source = tmp_path / 'map.SC2Map'
    source.write_bytes(b'map')
    session = NativeMultiplayerSession(source, output=tmp_path / 'run')
    with patch('mpsc2.native_session.platform.system', return_value='Darwin'), \
         patch('mpsc2.windows_session.enter_windows', new_callable=AsyncMock) as windows, \
         patch('mpsc2.native_session.validate_executable', side_effect=RuntimeError('mac validation reached')):
        with pytest.raises(RuntimeError, match='mac validation reached'):
            asyncio.run(session.__aenter__())
    windows.assert_not_awaited()


@pytest.mark.parametrize('report', [{'applied': False, 'error': 'wrong code'}, {'applied': True, 'pid': 16}])
def test_observation_guard_refusal_closes_before_client_use(report, tmp_path):
    process = WindowsProcess.__new__(WindowsProcess)
    process.helper = tmp_path / 'bridge.dll'
    process.output = tmp_path
    process.env = {'MPSC2_WINDOWS_GUARD_LOG': str(tmp_path / 'observation-guard.json')}
    process._process = SimpleNamespace(pid=17)
    with patch('mpsc2.native_session.NativeProcess._connect', new_callable=AsyncMock, return_value=object()), \
         patch('mpsc2.windows_session.load_bridge'), \
         patch('mpsc2.windows_session.wait_record', new_callable=AsyncMock, return_value=report):
        with pytest.raises(RuntimeError, match='observation guard refused'):
            asyncio.run(process._connect())


@pytest.mark.parametrize('observed,guarded', [(0, False), (3, False), (4, True), (8, True)])
@pytest.mark.parametrize('target_build', [75689, 93333])
def test_windows_replay_guards_affected_views(observed, guarded, target_build, tmp_path):
    from mpsc2.replay import run_replay
    replay = tmp_path / 'game.SC2Replay'
    replay.write_bytes(b'fixture')
    process = AsyncMock()
    process._arguments = {}
    from s2clientprotocol import sc2api_pb2 as api
    process.__aenter__.return_value.ping.return_value = api.Response(ping=api.ResponsePing(base_build=target_build))
    with patch('mpsc2.replay.get_replay_version', return_value=(f'Base{target_build}', 'A'*32)), \
         patch('mpsc2.replay.platform.system', return_value='Windows'), \
         patch('mpsc2.installation.detect_installation', return_value={'root': str(tmp_path)}), \
         patch('mpsc2.windows_session.validate_executable') as validate, \
         patch('mpsc2.windows_session.build_bridge', return_value=tmp_path / 'guard.dll') as build, \
         patch('mpsc2.windows_session.WindowsProcess', return_value=process) as windows, \
         patch('mpsc2.replay.OwnedSC2Process', return_value=process) as stock, \
         patch('mpsc2.protocol_compat.ProfileClient', return_value=AsyncMock()), \
         patch('mpsc2.replay._play', new_callable=AsyncMock, return_value={}):
        assert run_replay(None, replay, observed_id=observed) == {}
    assert windows.call_count == validate.call_count == 1
    assert build.call_count == int(guarded)
    stock.assert_not_called()
    assert process._arguments['-dataVersion'] == get_game_version(target_build).data_version
    if guarded:
        assert 'MPSC2_WINDOWS_GUARD_LOG' in windows.call_args.args[3]
        assert 'MPSC2_BRIDGE_DIR' not in windows.call_args.args[3]
        assert not windows.call_args.args[2].exists()


@pytest.mark.parametrize('observed', [0, 3, 4, 8])
def test_98370_replay_uses_verified_installed_data(observed, tmp_path):
    from mpsc2.replay import run_replay
    from s2clientprotocol import sc2api_pb2 as api
    data = get_game_version(98370).data_version
    replay = tmp_path/'game.SC2Replay'
    replay.touch()
    process = AsyncMock()
    process._arguments = {}
    controller = process.__aenter__.return_value
    controller.ping.return_value = api.Response(ping=api.ResponsePing(base_build=98370, data_version=data))
    with patch('mpsc2.replay.get_replay_version', return_value=('Base98370', data)), \
         patch('mpsc2.replay.platform.system', return_value='Windows'), \
         patch('mpsc2.installation.detect_installation', return_value={'root': str(tmp_path)}), \
         patch('mpsc2.windows_session.validate_executable'), \
         patch('mpsc2.windows_session.build_bridge', return_value=tmp_path/'guard.dll') as build, \
         patch('mpsc2.windows_session.WindowsProcess', return_value=process) as windows, \
         patch('mpsc2.replay.OwnedSC2Process') as stock, \
         patch('mpsc2.protocol_compat.ProfileClient', return_value=AsyncMock()), \
         patch('mpsc2.replay._play', new_callable=AsyncMock, return_value={}):
        assert run_replay(None, replay, observed_id=observed) == {}
    stock.assert_not_called()
    assert build.call_count == int(observed >= 4)
    assert ('MPSC2_WINDOWS_GUARD_LOG' in windows.call_args.args[3]) == (observed >= 4)
    assert '-dataVersion' not in process._arguments
    controller.ping.assert_awaited_once()
    controller.start_replay.assert_awaited_once()


@pytest.mark.parametrize('build,data', [(93333, '84197ED58A0329FA79CC9426E07E5FB3'), (98370, 'A'*32)])
def test_installed_content_mismatch_closes_replay_before_playback(build, data, tmp_path):
    from mpsc2.replay import run_replay
    from s2clientprotocol import sc2api_pb2 as api
    replay = tmp_path/'game.SC2Replay'
    replay.touch()
    process = AsyncMock()
    process._arguments = {}
    controller = process.__aenter__.return_value
    controller.ping.return_value = api.Response(ping=api.ResponsePing(base_build=build, data_version=data))
    with patch('mpsc2.replay.get_replay_version', return_value=('Base98370', get_game_version(98370).data_version)), \
         patch('mpsc2.replay.platform.system', return_value='Windows'), \
         patch('mpsc2.installation.detect_installation', return_value={'root': str(tmp_path)}), \
         patch('mpsc2.windows_session.validate_executable'), \
         patch('mpsc2.windows_session.WindowsProcess', return_value=process):
        with pytest.raises(RuntimeError, match='Installed SC2 data does not match'):
            run_replay(None, replay)
    controller.start_replay.assert_not_awaited()
    process.__aexit__.assert_awaited_once()


def test_launch_data_setting_is_profile_specific():
    process = SimpleNamespace(_arguments={})
    configure_data_version(process, WINDOWS_93333, get_game_version(93333).data_version)
    assert process._arguments['-dataVersion'] == '446907060311FB1CC29EB31E547BB9FD'
    configure_data_version(process, WINDOWS_98370, get_game_version(98370).data_version)
    assert '-dataVersion' not in process._arguments
