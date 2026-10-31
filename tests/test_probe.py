import asyncio
import json
import os
from unittest.mock import AsyncMock, patch

import pytest
from s2clientprotocol import sc2api_pb2 as api

from mpsc2.probe import main, probe


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
