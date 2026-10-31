import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from mpsc2.native_session import NativeProcess, build_observation_guard, observation_guard_environment
from mpsc2.replay import run_replay
from mpsc2.session import OwnedSC2Process


def test_guard_environment_is_local_and_preserves_host_bridge(tmp_path):
    environment = {'DYLD_INSERT_LIBRARIES': '/host/bridge.dylib', 'OTHER': 'value'}
    before = dict(os.environ)
    result = observation_guard_environment(environment, Path('/guard.dylib'), tmp_path)
    assert result['DYLD_INSERT_LIBRARIES'] == '/guard.dylib:/host/bridge.dylib'
    assert result['MPSC2_OBSERVATION_GUARD_LOG'] == str(tmp_path/'observation-guard.json')
    assert environment == {'DYLD_INSERT_LIBRARIES': '/host/bridge.dylib', 'OTHER': 'value'}
    assert dict(os.environ) == before


@pytest.mark.parametrize('applied', [False, True])
def test_native_connect_waits_for_verified_guard_before_api(applied, tmp_path):
    process = NativeProcess.__new__(NativeProcess)
    process.env = {'MPSC2_OBSERVATION_GUARD_LOG': str(tmp_path/'observation-guard.json')}
    process.output, process._process = tmp_path, Mock()
    process._process.pid = 123
    report = {'applied': applied, 'pid': 123, 'error': 'unexpected observation instructions'}
    async def connect():
        assert process.observation_guard is report
        return 'connected'
    with patch('mpsc2.native_session.wait_record', new_callable=AsyncMock, return_value=report), \
         patch.object(OwnedSC2Process, '_connect', new_callable=AsyncMock, side_effect=connect) as upstream:
        if applied:
            assert asyncio.run(process._connect()) == 'connected'
            upstream.assert_awaited_once()
        else:
            with pytest.raises(RuntimeError, match='unexpected observation instructions'):
                asyncio.run(process._connect())
            upstream.assert_not_called()


def test_stale_guard_report_cannot_authorize_new_process(tmp_path):
    process = NativeProcess.__new__(NativeProcess)
    process.env = {'MPSC2_OBSERVATION_GUARD_LOG': str(tmp_path/'observation-guard.json')}
    process.output, process._process = tmp_path, SimpleNamespace(pid=123)
    with patch('mpsc2.native_session.wait_record', new_callable=AsyncMock, return_value={'applied': True, 'pid': 122}), \
         patch.object(OwnedSC2Process, '_connect', new_callable=AsyncMock) as upstream:
        with pytest.raises(RuntimeError, match='another process'):
            asyncio.run(process._connect())
        upstream.assert_not_called()


def test_unguarded_stock_process_connects_normally():
    process = NativeProcess.__new__(NativeProcess)
    process.env = {}
    with patch('mpsc2.native_session.wait_record') as guard, \
         patch.object(OwnedSC2Process, '_connect', new_callable=AsyncMock, return_value='stock'):
        assert asyncio.run(process._connect()) == 'stock'
    guard.assert_not_called()


def test_guard_build_failure_preserves_diagnostic_and_refuses_launch(tmp_path):
    with patch('mpsc2.native_session.subprocess.run', return_value=SimpleNamespace(
            returncode=1, stdout='', stderr='compiler diagnostic')):
        with pytest.raises(RuntimeError, match='compiler diagnostic'):
            build_observation_guard(tmp_path)
    assert 'compiler diagnostic' in (tmp_path/'observation-guard-build.log').read_text()


@pytest.mark.parametrize('observed,system,build,guarded', [
    (0, 'Darwin', 'Base96883', False), (3, 'Darwin', 'Base96883', False),
    (4, 'Darwin', 'Base96883', True), (8, 'Darwin', 'Base96883', True),
    (4, 'Linux', 'Base96883', False), (4, 'Darwin', 'Base12345', False),
])
def test_replay_guards_only_affected_build_and_view(observed, system, build, guarded, tmp_path):
    replay = tmp_path/'game.SC2Replay'
    replay.write_bytes(b'fixture')
    process = AsyncMock()
    process._arguments = {}
    with patch('mpsc2.replay.get_replay_version', return_value=(build, 'A'*32)), \
         patch('mpsc2.replay.platform.system', return_value=system), \
         patch('mpsc2.native_session.validate_executable') as validate, \
         patch('mpsc2.native_session.build_observation_guard', return_value=tmp_path/'guard.dylib') as compile_guard, \
         patch('mpsc2.native_session.NativeProcess', return_value=process) as native, \
         patch('mpsc2.replay.OwnedSC2Process', return_value=process) as stock, \
         patch('mpsc2.replay.Client'), patch('mpsc2.replay._play', new_callable=AsyncMock, return_value={}):
        assert run_replay(None, replay, observed_id=observed) == {}
    assert native.call_count == validate.call_count == compile_guard.call_count == int(guarded)
    assert stock.call_count == int(not guarded)
    process.__aexit__.assert_awaited_once()
    if guarded:
        assert process._arguments['-dataVersion'] == 'A'*32
        assert 'MPSC2_OBSERVATION_GUARD_LOG' in native.call_args.args[3]
        assert not native.call_args.args[2].exists()  # temporary native artifacts removed


def test_replay_unknown_executable_is_refused_before_launch(tmp_path):
    replay = tmp_path/'game.SC2Replay'
    replay.write_bytes(b'fixture')
    with patch('mpsc2.replay.get_replay_version', return_value=('Base96883', 'A'*32)), \
         patch('mpsc2.replay.platform.system', return_value='Darwin'), \
         patch('mpsc2.native_session.validate_executable', side_effect=RuntimeError('Unsupported SC2 executable')), \
         patch('mpsc2.native_session.NativeProcess') as launch:
        with pytest.raises(RuntimeError, match='Unsupported SC2 executable'):
            run_replay(None, replay, observed_id=4)
    launch.assert_not_called()
