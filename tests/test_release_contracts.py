"""Release contracts at the upstream/multiplayer integration boundary."""
import asyncio
import ast
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sc2.bot_ai import BotAI
from sc2.data import Race, Result
from sc2.player import Bot, Computer

import mpsc2
from mpsc2.cli import main as cli
from mpsc2.session import OwnedSC2Process, MultiplayerSession
from mpsc2.standard import run_standard_async
from mpsc2.native_session import NativeMultiplayerSession, RecordedClient
from s2clientprotocol import sc2api_pb2 as api


def compatibility_modules():
    root = Path(mpsc2.__file__).parent
    for path in sorted(root.rglob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith('sc2.') and any(n.name == '*' for n in node.names):
                yield path.relative_to(root).with_suffix('').as_posix().replace('/', '.'), node.module


@pytest.mark.parametrize('local,upstream', list(compatibility_modules()))
def test_every_export_in_compatibility_module_keeps_upstream_identity(local, upstream):
    original = importlib.import_module(upstream)
    shim = importlib.import_module('mpsc2.' + local)
    names = getattr(original, '__all__', [n for n in vars(original) if not n.startswith('_')])
    for name in names:
        assert getattr(shim, name) is getattr(original, name), (local, name)


@pytest.mark.parametrize('failure', [False, True])
def test_owned_process_always_cleans_after_websocket_close(failure):
    process = OwnedSC2Process.__new__(OwnedSC2Process)
    process._close_connection = AsyncMock(side_effect=OSError('socket close failed') if failure else None)
    process._clean = Mock()
    if failure:
        with pytest.raises(OSError, match='socket close failed'):
            asyncio.run(process.__aexit__(None, None, None))
    else:
        asyncio.run(process.__aexit__(None, None, None))
    process._clean.assert_called_once()


def test_failed_connect_cleans_even_if_socket_close_fails():
    process = OwnedSC2Process.__new__(OwnedSC2Process)
    process._launch = Mock()
    process._connect = AsyncMock(side_effect=RuntimeError('connect failed'))
    process._close_connection = AsyncMock(side_effect=OSError('close failed'))
    process._clean = Mock()
    with pytest.raises((RuntimeError, OSError)):
        asyncio.run(process.__aenter__())
    process._clean.assert_called_once()


@pytest.mark.parametrize('provided', [False, True])
@pytest.mark.parametrize('failure', [False, True])
def test_standard_async_releases_only_ports_it_owns(provided, failure):
    ports = Mock()
    host = AsyncMock(side_effect=RuntimeError('host failed') if failure else None, return_value=Result.Tie)
    guest = AsyncMock(return_value=Result.Tie)
    players = [Bot(Race.Terran, BotAI()) for _ in range(2)]
    async def run():
        return await run_standard_async(object(), players, False, ports if provided else None,
                                        None, None, None, None, None, False)
    with patch('mpsc2.standard.Portconfig', return_value=ports), \
         patch('sc2.main._host_game', host), patch('sc2.main._join_game', guest):
        if failure:
            with pytest.raises(RuntimeError, match='host failed'):
                asyncio.run(run())
        else:
            assert asyncio.run(run()) == [Result.Tie, Result.Tie]
    assert ports.clean.call_count == (0 if provided else 1)


def test_standard_async_one_bot_keeps_computer_and_options():
    players = [Bot(Race.Terran, BotAI()), Computer(Race.Zerg)]
    with patch('sc2.main._host_game', new_callable=AsyncMock, return_value=Result.Victory) as host:
        result = asyncio.run(run_standard_async('map', players, True, None, Path('out.SC2Replay'),
                                                30, None, 7, None, True))
    assert result is Result.Victory
    assert host.call_args.args == ('map', players)
    assert host.call_args.kwargs['save_replay_as'] == 'out.SC2Replay'
    assert host.call_args.kwargs['realtime'] and host.call_args.kwargs['disable_fog']


def test_session_releases_ports_even_when_process_cleanup_fails(tmp_path):
    path = tmp_path / 'map.SC2Map'
    path.write_bytes(b'fixture')
    session = MultiplayerSession(path)
    ports = session.ports = Mock()
    session.stack = SimpleNamespace(aclose=AsyncMock(side_effect=OSError('process close failed')))
    with pytest.raises(OSError, match='process close failed'):
        asyncio.run(session.close())
    ports.clean.assert_called_once()
    assert session.ports is None


def test_cli_maps_and_version_without_sc2(capsys):
    assert cli(['maps']) == 0
    output = capsys.readouterr().out
    assert all(name in output for name in mpsc2.maps.available())
    with pytest.raises(SystemExit) as result:
        cli(['--version'])
    assert result.value.code == 0
    assert mpsc2.__version__ in capsys.readouterr().out


@pytest.mark.parametrize('ready', [False, True])
def test_cli_doctor_exit_status_matches_readiness(ready, capsys):
    with patch('mpsc2.cli.get_capabilities', return_value={'multiplayer': {'ready': ready}}):
        assert cli(['doctor']) == (0 if ready else 1)
    assert '"ready"' in capsys.readouterr().out


def test_cli_replay_forwards_observer_and_timing(capsys):
    with patch('mpsc2.cli.run_replay', return_value={3: Result.Victory}) as run:
        assert cli(['replay', 'game.SC2Replay', '--fast', '--observed-id', '3', '--step-size', '16', '--max-game-loop', '100']) == 0
    assert run.call_args.args == (None, 'game.SC2Replay')
    assert run.call_args.kwargs == dict(realtime=False, observed_id=3, speed=1.0, step_size=16, max_game_loop=100)
    assert 'Victory' in capsys.readouterr().out


def test_native_launch_honors_per_bot_selection_option(tmp_path):
    players = [Bot(Race.Terran, BotAI()) for _ in range(2)]
    players[0].ai.raw_affects_selection = True
    with patch('mpsc2.main.NativeMultiplayerSession', side_effect=RuntimeError('test launch boundary')) as session:
        with pytest.raises(RuntimeError, match='test launch boundary'):
            mpsc2.run_game('MPSC2TeamArena', players, output_dir=tmp_path/'run')
    assert session.call_args.kwargs['raw_affects_selection'] == [True, None]


@pytest.mark.parametrize('flag', [False, True])
def test_join_journal_records_actual_protocol_selection_option(tmp_path, flag):
    client = RecordedClient(Mock(), tmp_path/'api.jsonl')
    client.raw_affects_selection = flag
    response = api.Response(join_game=api.ResponseJoinGame(player_id=1), status=api.in_game)
    with patch('sc2.protocol.Protocol._execute', new_callable=AsyncMock, return_value=response) as execute:
        assert asyncio.run(client.join_game(race=Race.Terran)) == 1
    assert execute.call_args.kwargs['join_game'].options.raw_affects_selection is flag
    assert json.loads((tmp_path/'api.jsonl').read_text())['raw_affects_selection'] is flag


def test_selection_option_rejected_before_launch(tmp_path):
    players = [Bot(Race.Terran, BotAI()) for _ in range(2)]
    players[0].ai.raw_affects_selection = 'yes'
    with pytest.raises(ValueError, match='raw_affects_selection'):
        mpsc2.run_game('MPSC2TeamArena', players, output_dir=tmp_path/'run')
    assert not (tmp_path/'run').exists()
    source = mpsc2.maps.get('MPSC2TeamArena').path
    with pytest.raises(ValueError, match='raw_affects_selection'):
        NativeMultiplayerSession(source, players=2, output=tmp_path/'low-level', raw_affects_selection=[True])
