import asyncio
import json
import os
from unittest.mock import AsyncMock, Mock, patch

import pytest
from aiohttp import web
from s2clientprotocol import sc2api_pb2 as api

from mpsc2.probe import main, probe, probe_connection
from mpsc2.session import SC2LaunchError


def test_probe_resolves_packaged_map_outside_checkout(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch('mpsc2.probe.detect_installation', return_value={'ready': True}), \
         patch('mpsc2.probe.probe', new_callable=AsyncMock) as run:
        assert main(['--output', 'probe.json']) == 0
    assert run.call_args.args[0].is_file()
    report = json.loads((tmp_path / 'probe.json').read_text(encoding='utf-8'))
    assert len(report['map_sha256']) == 64
    assert report['multiplayer_gameplay_confirmed'] is False


def test_missing_installation_writes_actionable_report_without_launch(tmp_path):
    output = tmp_path / 'probe.json'
    with patch('mpsc2.probe.detect_installation', return_value={'ready': False, 'errors': ['Set SC2PATH']}), \
         patch('mpsc2.probe.OwnedSC2Process') as process:
        assert main(['--output', str(output)]) == 1
    process.assert_not_called()
    assert 'Set SC2PATH' in json.loads(output.read_text())['probe_error']


@pytest.mark.parametrize('fail', [False, True])
def test_probe_launch_uses_detected_root_and_restores_environment(tmp_path, monkeypatch, fail):
    monkeypatch.delenv('SC2PATH', raising=False)
    root = str(tmp_path / 'Games 游戏')
    async def check_root(*args):
        assert os.environ['SC2PATH'] == root
        if fail:
            raise RuntimeError('engine failure')
    with patch('mpsc2.probe.detect_installation', return_value={'ready': True, 'root': root}), \
         patch('mpsc2.probe.probe', side_effect=check_root):
        assert main(['--output', str(tmp_path / 'probe.json')]) == int(fail)
    assert 'SC2PATH' not in os.environ


def test_probe_preserves_existing_report(tmp_path):
    output = tmp_path / 'probe.json'
    output.write_text('prior evidence')
    with pytest.raises(SystemExit):
        main(['--output', str(output)])
    assert output.read_text() == 'prior evidence'


@pytest.mark.parametrize('timeout', ['0', '-1', 'nan', 'inf'])
def test_probe_rejects_unbounded_timeout(timeout):
    with pytest.raises(SystemExit):
        main(['--timeout', timeout])


def test_probe_records_four_client_rejections_and_stops_at_accepted_create(tmp_path):
    source = tmp_path / 'map.SC2Map'
    source.write_bytes(b'fixture')
    process = AsyncMock()
    controller = process.__aenter__.return_value
    controller.ping.return_value = api.Response(ping=api.ResponsePing(base_build=99999, game_version='fixture'))
    rejection = api.Response(create_game=api.ResponseCreateGame(
        error=api.ResponseCreateGame.InvalidPlayerSetup, error_details='Only 1v1 is supported when using multiple agents'))
    controller._execute.side_effect = [rejection, rejection, api.Response(create_game=api.ResponseCreateGame())]
    report = {'cases': []}
    with patch('mpsc2.probe.OwnedSC2Process', return_value=process):
        asyncio.run(probe(source, 5, report))
    assert report['sc2']['base_build'] == 99999
    assert [c['api_players'] for c in report['cases']] == [4, 4, 2]
    assert [c['accepted'] for c in report['cases']] == [False, False, True]
    assert [c['realtime'] for c in report['cases']] == [False, True, False]
    assert report['cases'][0]['error_name'] == 'InvalidPlayerSetup'
    assert [p.type for p in controller._execute.call_args.kwargs['create_game'].player_setup] == [api.Participant] * 2
    process.__aexit__.assert_awaited_once()


def test_probe_records_engine_exit_before_api(tmp_path):
    process = AsyncMock()
    process.__aenter__.side_effect = SC2LaunchError(
        Mock(pid=123, returncode=1, args=['/fixture/SC2']))
    report = {'cases': []}
    with patch('mpsc2.probe.OwnedSC2Process', return_value=process):
        with pytest.raises(SC2LaunchError):
            asyncio.run(probe(tmp_path / 'unused.SC2Map', 1, report))
    assert report['startup'] == {'api_connected': False, 'pid': 123, 'returncode': 1,
                                 'executable': '/fixture/SC2'}
    assert report['cases'] == [] and 'sc2' not in report


def test_probe_names_startup_timeout(tmp_path):
    process = AsyncMock()
    async def waiting():
        await asyncio.Event().wait()
    process.__aenter__.side_effect = waiting
    with patch('mpsc2.probe.OwnedSC2Process', return_value=process):
        with pytest.raises(TimeoutError, match='SC2 API startup did not complete'):
            asyncio.run(probe(tmp_path / 'unused.SC2Map', .02, {'cases': []}))


def test_owned_probe_refuses_wrong_build_before_create(tmp_path):
    process = AsyncMock()
    controller = process.__aenter__.return_value
    controller.ping.return_value = api.Response(ping=api.ResponsePing(base_build=96883))
    report = {'cases': []}
    with patch('mpsc2.probe.OwnedSC2Process', return_value=process):
        with pytest.raises(RuntimeError, match='Expected Base98310.*Base96883'):
            asyncio.run(probe(tmp_path / 'unused.SC2Map', 1, report, expected_base_build=98310))
    controller._execute.assert_not_called()
    assert report['sc2']['base_build'] == 96883
    assert report['cases'] == []
    process.__aexit__.assert_awaited_once()


@pytest.mark.parametrize('mode', ['valid', 'wrong-build', 'wrong-id', 'missing-ping', 'text', 'stall'])
def test_attached_probe_wire_protocol_and_cleanup(mode):
    async def run():
        requests = []
        disconnected = asyncio.Event()

        async def handler(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            try:
                async for message in ws:
                    req = api.Request.FromString(message.data)
                    requests.append(req.WhichOneof('request'))
                    if mode == 'stall':
                        continue
                    if mode == 'text':
                        await ws.send_str('not SC2')
                    else:
                        response = api.Response(id=2 if mode == 'wrong-id' else req.id)
                        if mode != 'missing-ping':
                            response.ping.base_build = 96883 if mode == 'wrong-build' else 98310
                            response.ping.game_version = 'fixture'
                        await ws.send_bytes(response.SerializeToString())
            finally:
                disconnected.set()
            return ws

        app = web.Application()
        app.router.add_get('/sc2api', handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        report = {'cases': []}
        try:
            port = site._server.sockets[0].getsockname()[1]
            if mode == 'valid':
                await probe_connection(port, 2, report, 98310)
                assert report['sc2']['base_build'] == 98310
            else:
                error, match = {
                    'wrong-build': (RuntimeError, 'Expected Base98310.*Base96883'),
                    'wrong-id': (RuntimeError, 'response ID'),
                    'missing-ping': (RuntimeError, 'valid SC2 Ping'),
                    'text': (RuntimeError, 'binary WebSocket'),
                    'stall': (TimeoutError, 'connection/Ping'),
                }[mode]
                with pytest.raises(error, match=match):
                    await asyncio.wait_for(probe_connection(port, .1, report, 98310), 2)
            await asyncio.wait_for(disconnected.wait(), 2)
            assert requests == ['ping']  # Never CreateGame, LeaveGame or Quit.
            assert report['startup']['process_owned'] is False
            assert report['startup']['api_connected'] is True
            assert report['cases'] == []
        finally:
            await runner.cleanup()

    asyncio.run(run())


@pytest.mark.parametrize('fail', [False, True])
def test_attach_cli_needs_no_installation_and_preserves_report(tmp_path, fail):
    output = tmp_path / 'attach.json'
    with patch('mpsc2.probe.detect_installation') as detect, \
         patch('mpsc2.probe.maps.get') as get_map, \
         patch('mpsc2.probe.OwnedSC2Process') as process, \
         patch('mpsc2.probe.probe_connection', new_callable=AsyncMock) as connect:
        if fail:
            connect.side_effect = RuntimeError('fixture failure')
        assert main(['--attach-port', '5001', '--expected-base-build', '98310',
                     '--output', str(output)]) == int(fail)
    detect.assert_not_called()
    get_map.assert_not_called()
    process.assert_not_called()
    assert connect.call_args.args[0:2] == (5001, 60)
    assert connect.call_args.args[3] == 98310
    report = json.loads(output.read_text())
    assert report['expected_base_build'] == 98310
    assert report['cases'] == []
    assert report['scope'].startswith('Ping only')
    assert ('probe_error' in report) == fail


@pytest.mark.parametrize('args', [
    ['--attach-port', '0'], ['--attach-port', '65536'], ['--expected-base-build', '0'],
    ['--expected-base-build', '-1'],
])
def test_probe_rejects_invalid_attach_options(args):
    with pytest.raises(SystemExit):
        main(args)


def test_attached_probe_does_not_wait_for_peer_close_handshake():
    async def run():
        release = asyncio.Event()

        async def handler(request):
            ws = web.WebSocketResponse(autoclose=False)
            await ws.prepare(request)
            message = await ws.receive()
            req = api.Request.FromString(message.data)
            await ws.send_bytes(api.Response(id=req.id, ping=api.ResponsePing(base_build=98310)).SerializeToString())
            # Reply to Ping but deliberately do not read/respond to Close.
            await release.wait()
            return ws

        app = web.Application()
        app.router.add_get('/sc2api', handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        try:
            port = site._server.sockets[0].getsockname()[1]
            report = {}
            await asyncio.wait_for(probe_connection(port, .5, report, 98310), 1)
            assert report['sc2']['base_build'] == 98310
        finally:
            release.set()
            await runner.cleanup()

    asyncio.run(run())
