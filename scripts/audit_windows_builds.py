"""Opt-in audit of exact local Windows builds without loading native helpers.

Checks the production executable guard, reads the running engine's instruction
signatures, probes stock CreateGame, and runs a two-client BotAI fixture through
the shared MPSC2 orchestration. This does not authorize a new native backend.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import ctypes as c
import json
import os
from pathlib import Path
import platform
import sys
from unittest.mock import patch

from loguru import logger
import mpyq
import psutil
from sc2.portconfig import Portconfig
from sc2.versions import VERSIONS
from s2clientprotocol import sc2api_pb2 as api

from mpsc2 import maps, run_game_async
from mpsc2.data import Race
from mpsc2.player import Bot
from mpsc2.installation import detect_installation, file_sha256
from mpsc2.native_session import RecordedClient
from mpsc2.session import MultiplayerSession, barrier
from mpsc2.windows_session import WindowsProcess, validate_executable
from mpsc2.versions import WINDOWS_93333
from validate_alpha import assert_processes_closed
from validate_player_counts import CountBot


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def inspect_signatures(process):
    """Read only this launcher's child; never load a DLL or write game memory."""
    handle = int(process._process._handle)
    ps = c.WinDLL('psapi', use_last_error=True)
    ps.EnumProcessModules.argtypes = [c.c_void_p, c.c_void_p, c.c_ulong, c.c_void_p]
    modules = (c.c_void_p * 1024)()
    needed = c.c_ulong()
    if not ps.EnumProcessModules(handle, modules, c.sizeof(modules), c.byref(needed)):
        raise c.WinError(c.get_last_error())
    base = modules[0]
    kernel = c.WinDLL('kernel32', use_last_error=True)
    kernel.ReadProcessMemory.argtypes = [c.c_void_p, c.c_void_p, c.c_void_p, c.c_size_t, c.c_void_p]
    layout = WINDOWS_93333.windows_layout
    signatures = {name: getattr(layout, name) for name in (
        'lobby_check', 'readiness_check', 'opponent_upgrade', 'own_upgrade', 'upgrade_cleanup')}
    results = {}
    for name, signature in signatures.items():
        rva, expected = signature.rva, signature.expected.hex()
        data = c.create_string_buffer(len(bytes.fromhex(expected)))
        got = c.c_size_t()
        readable = bool(kernel.ReadProcessMemory(handle, base+rva, data, len(data), c.byref(got))) and got.value == len(data)
        actual = data.raw.hex() if readable else None
        results[name] = {'rva': hex(rva), 'expected_base93333': expected,
                         'actual': actual, 'matches': actual == expected}
    return results


def make_process(root, build, output, index, data_hash):
    env = {k: v for k, v in os.environ.items() if not k.startswith('MPSC2_') and k != 'DYLD_INSERT_LIBRARIES'}
    process = WindowsProcess(root/f'Versions/Base{build}/SC2_x64.exe', root, output, env, index)
    if data_hash:
        process._arguments['-dataVersion'] = data_hash
    return process


async def checked_ping(controller, build, timeout):
    ping = (await barrier([controller.ping()], timeout, [controller]))[0].ping
    assert ping.base_build == build, f'Expected Base{build}, actually running Base{ping.base_build}'
    return {'game_version': ping.game_version, 'base_build': ping.base_build, 'data_version': ping.data_version}


async def stock_probe(root, build, output, data_hash, timeout):
    process = make_process(root, build, output, 0, data_hash)
    report = {'native_helper_loaded': False, 'memory_writes': False, 'cases': []}
    try:
        async with process as controller:
            report['process'] = {'pid': process._process.pid, 'process_create_time': psutil.Process(process._process.pid).create_time()}
            report['engine'] = await checked_ping(controller, build, timeout)
            report['base93333_signatures'] = inspect_signatures(process)
            for count, realtime in ((4, False), (4, True), (2, False)):
                request = api.RequestCreateGame(local_map=api.LocalMap(map_path=str(maps.get('MPSC2TeamArena').path)), realtime=realtime)
                for _ in range(count):
                    request.player_setup.add(type=api.Participant)
                response = (await barrier([controller._execute(create_game=request)], timeout, [controller]))[0]
                assert not response.error and response.HasField('create_game'), str(response)
                result = response.create_game
                accepted = not result.HasField('error')
                report['cases'].append({'players': count, 'realtime': realtime, 'accepted': accepted,
                    'error': result.error_details, 'error_code': result.error if not accepted else None})
                if accepted:
                    break
    finally:
        if 'process' in report:
            assert_processes_closed({'players': [report['process']]})
            report['owned_process_closed'] = True
        output.mkdir(parents=True, exist_ok=True)
        write(output/'probe.json', report)
    return report


def stock_session_factory(root, build, data_hash):
    class ExactBuildStockSession(MultiplayerSession):
        """Test-only stock two-player hosting; contains no native workaround."""
        def __init__(self, map_path, **options):
            assert options['players'] == 2
            super().__init__(map_path, players=2, seed=options['seed'], disable_fog=options['disable_fog'], timeout=options['timeout'])
            self.output = options['output']
            self.realtime = options['realtime']
            self.options = options
            self.native_metadata = {'backend': 'test-only stock API', 'build': str(build), 'native_helper_loaded': False, 'processes': []}

        async def __aenter__(self):
            self.output.mkdir(parents=True, exist_ok=False)
            try:
                self.ports = Portconfig(guests=1)
                for i in range(2):
                    process = make_process(root, build, self.output/f'client-{i}', i, data_hash)
                    self.processes.append(process)
                    controller = await asyncio.wait_for(self.stack.enter_async_context(process), self.timeout)
                    engine = await checked_ping(controller, build, self.timeout)
                    self.controllers.append(controller)
                    client = RecordedClient(controller._ws, self.output/f'client-{i}/api.jsonl')
                    self.clients.append(client)
                    self.native_metadata['processes'].append({'pid': process._process.pid,
                        'process_create_time': psutil.Process(process._process.pid).create_time(),
                        'api_port': process._port, 'engine': engine})
                request = api.RequestCreateGame(local_map=api.LocalMap(map_path=str(self.map_path)),
                    realtime=self.realtime, random_seed=self.seed, disable_fog=self.disable_fog)
                for _ in range(2):
                    request.player_setup.add(type=api.Participant)
                response = (await self.call([self.controllers[0]._execute(create_game=request)]))[0]
                if response.create_game.HasField('error'):
                    raise RuntimeError(str(response.create_game))
                self.player_ids = await self.call([client.join_game(race=Race.Terran, portconfig=self.ports) for client in self.clients])
                assert sorted(self.player_ids) == [1, 2]
                return self
            except BaseException:
                await self.close()
                raise
            finally:
                write(self.output/'native-session.json', self.native_metadata)
    return ExactBuildStockSession


def verify_stock_game(folder, build, realtime):
    game = json.loads((folder/'result.json').read_text())
    assert game['status'] == 'completed'
    assert all(p['engine']['base_build'] == build for p in game['players'])
    for key in ('player_id', 'pid', 'api_port'):
        assert len({p[key] for p in game['players']}) == 2
    assert_processes_closed(game)
    requests = []
    for i in range(2):
        counts = Counter(json.loads(line)['request'] for line in (folder/f'session/client-{i}/api.jsonl').read_text().splitlines())
        assert counts['action'] > 0 and counts['observation'] > 0 and counts['debug'] == 0
        assert counts['step'] == 0 if realtime else counts['step'] > 0
        requests.append(dict(counts))
    archive = mpyq.MPQArchive(str(folder/'game.SC2Replay'), listfile=False)
    try:
        metadata = json.loads(archive.read_file('replay.gamemetadata.json'))
    finally:
        archive.file.close()
    assert metadata['BaseBuild'] == f'Base{build}'
    assert sorted(p['PlayerID'] for p in metadata['Players']) == [1, 2]
    return {'passed': True, 'request_counts': requests, 'replay_metadata': metadata,
            'independent_processes_ports_ids': True, 'owned_processes_closed': True}


async def audit_build(root, build, output, timeout):
    executable = root/f'Versions/Base{build}/SC2_x64.exe'
    result = {'requested_build': build, 'executable': str(executable), 'executable_exists': executable.is_file()}
    if not executable.is_file():
        result['status'] = 'not_testable_missing_executable'
        write(output/'audit.json', result)
        return result
    result['sha256_before'] = file_sha256(executable)
    try:
        validate_executable(executable)
        result['production_guard'] = {'accepted': True}
    except RuntimeError as error:
        result['production_guard'] = {'accepted': False, 'error': str(error)}
    version = next((v for v in VERSIONS if v['base-version'] == build), {})
    data_hash = version.get('data-hash')
    result['requested_data_version'] = data_hash
    try:
        result['stock_probe'] = await asyncio.wait_for(stock_probe(root, build, output/'probe', data_hash, timeout), timeout*2)
        result['two_player_games'] = []
        for realtime in (False, True):
            folder = output/('realtime' if realtime else 'stepped')
            bots = [CountBot('arena'), CountBot('arena')]
            with patch('mpsc2.main.NativeMultiplayerSession', stock_session_factory(root, build, data_hash)):
                results = await run_game_async('MPSC2TeamArena', [Bot(Race.Terran, bot) for bot in bots],
                    team_ids=[0,1], realtime=realtime, game_time_limit=5, step_size=8,
                    output_dir=folder, save_replay_as=folder/'game.SC2Replay', timeout=timeout)
            game = json.loads((folder/'result.json').read_text())
            verification = verify_stock_game(folder, build, realtime)
            assert all(bot.steps > 0 and bot.moved and bot.ended for bot in bots)
            assert all(bot.result == result.name for bot, result in zip(bots, results))
            assert not bots[0].owned_tags & bots[1].owned_tags
            result['two_player_games'].append({'realtime': realtime, 'passed': True,
                'results': [r.name for r in results], 'native_ids': [p['player_id'] for p in game['players']],
                'movement_observed': True, 'owned_processes_closed': True,
                'verification': verification,
                'scope': 'Shared MPSC2 BotAI orchestration with an exact-build stock API test launcher; not native 3–8-player support'})
        result['status'] = 'audit_completed'
    except Exception as error:
        result['status'] = 'audit_failed'
        result['error'] = f'{type(error).__name__}: {error}'
    finally:
        result['sha256_after'] = file_sha256(executable)
        result['installed_executable_unchanged'] = result['sha256_before'] == result['sha256_after']
        write(output/'audit.json', result)
    return result


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--builds', nargs='+', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--timeout', type=float, default=60)
    args = parser.parse_args()
    if platform.system() != 'Windows':
        parser.error('This audit requires Windows')
    root = (args.root or Path(detect_installation()['root'])).resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    logger.remove()
    logger.add(sys.stderr, level='INFO')
    records = []
    for build in args.builds:
        output = args.output/f'Base{build}'
        output.mkdir()
        print(f'Auditing Base{build}', flush=True)
        result = await audit_build(root, build, output, args.timeout)
        records.append(result)
        write(args.output/'summary.json', records)
        print(json.dumps(result), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
