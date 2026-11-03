"""Probe the installed engine's CreateGame limits without assuming client support."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys

import aiohttp
from loguru import logger
from s2clientprotocol import sc2api_pb2 as sc_pb
from sc2.data import Race

from .session import OwnedSC2Process, SC2LaunchError, barrier
from . import maps
from .installation import detect_installation


def _record_ping(response, report, expected_base_build=None):
    if response.error or not response.HasField('ping') or not response.ping.base_build:
        raise RuntimeError('Endpoint did not return a valid SC2 Ping response')
    ping = response.ping
    report['sc2'] = {'game_version': ping.game_version, 'base_build': ping.base_build,
                     'data_version': ping.data_version}
    if expected_base_build is not None and ping.base_build != expected_base_build:
        raise RuntimeError(f'Expected Base{expected_base_build}, but the API reports Base{ping.base_build}; '
                           'no game was created')


async def probe_connection(port, timeout, report, expected_base_build=None):
    """Ping an already running local engine; never create, leave or quit its game.

    Use the wire protocol directly so cancellation cannot enter upstream's
    response-draining loop. The one deadline covers connection and response.
    """
    url = f'ws://127.0.0.1:{port}/sc2api'
    report['startup'] = {'api_connected': False, 'process_owned': False, 'endpoint': url}

    async def connect():
        async with aiohttp.ClientSession(trust_env=False) as session:
            ws = await session.ws_connect(url, max_msg_size=1024 * 1024)
            try:
                report['startup']['api_connected'] = True
                request = sc_pb.Request(id=1, ping=sc_pb.RequestPing())
                await ws.send_bytes(request.SerializeToString())
                message = await ws.receive()
                if message.type != aiohttp.WSMsgType.BINARY:
                    raise RuntimeError('SC2 Ping expected a binary WebSocket response')
                response = sc_pb.Response.FromString(message.data)
                if response.HasField('id') and response.id != request.id:
                    raise RuntimeError('SC2 Ping response ID does not match its request')
                _record_ping(response, report, expected_base_build)
            finally:
                # Close our transport first: an unresponsive peer must not add
                # a WebSocket close-handshake wait after the probe's deadline.
                await session.close()
                await ws.close()

    try:
        await asyncio.wait_for(connect(), timeout)
    except asyncio.TimeoutError as exc:
        raise TimeoutError(f'SC2 API connection/Ping did not complete within {timeout}s') from exc


async def probe(map_path, timeout, report, expected_base_build=None):
    process = OwnedSC2Process(fullscreen=False, resolution=(640, 480))
    report['startup'] = {'api_connected': False}

    async def run_cases():
        async with process as controller:
            report['startup']['api_connected'] = True
            response = (await barrier([controller.ping()], timeout, [controller]))[0]
            _record_ping(response, report, expected_base_build)
            # A stock 1v1 baseline must have exactly two total participants:
            # adding two Computers would also trigger the engine's 1v1 limit.
            for api_players, computer_players, realtime in [(4, 0, False), (4, 0, True), (2, 0, False), (1, 3, False)]:
                request = sc_pb.RequestCreateGame(
                    local_map=sc_pb.LocalMap(map_path=str(map_path.resolve()), map_data=map_path.read_bytes()),
                    realtime=realtime, random_seed=1,
                )
                for _ in range(api_players):
                    request.player_setup.add(type=sc_pb.Participant)
                for _ in range(computer_players):
                    request.player_setup.add(type=sc_pb.Computer, race=Race.Terran.value, difficulty=sc_pb.VeryEasy)
                response = (await barrier([controller._execute(create_game=request)], timeout, [controller]))[0]
                if response.error or not response.HasField('create_game'):
                    raise RuntimeError(f'Invalid CreateGame response: {response}')
                has_error = response.create_game.HasField("error")
                entry = {"api_players": api_players, "computer_players": computer_players,
                         "realtime": realtime, "accepted": not has_error,
                         "error_code": response.create_game.error if has_error else None,
                         "error_name": sc_pb.ResponseCreateGame.Error.Name(response.create_game.error) if has_error else None,
                         "error_details": response.create_game.error_details}
                report["cases"].append(entry)
                print(json.dumps(entry), flush=True)
                # A successful CreateGame changes state: do not issue another on
                # this process before joining/leaving. The accepted case is last
                # on currently tested engines; stop early if support improves.
                if entry["accepted"]:
                    break

    try:
        await asyncio.wait_for(run_cases(), timeout)
    except SC2LaunchError as exc:
        report['startup'].update(pid=exc.pid, returncode=exc.returncode, executable=exc.executable)
        raise
    except asyncio.TimeoutError as exc:
        # asyncio.TimeoutError became an alias of the builtin only in 3.11.
        phase = 'SC2 protocol probe' if report['startup']['api_connected'] else 'SC2 API startup'
        raise TimeoutError(f'{phase} did not complete within {timeout}s') from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", default="MPSC2TeamArena", help="Bundled name or path to a four-slot SC2Map")
    parser.add_argument("--output", type=Path, default=Path("reports/engine-capabilities.json"))
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument('--attach-port', type=int,
                        help='Only Ping an already running local SC2 API; do not launch, create a game or quit')
    parser.add_argument('--expected-base-build', type=int,
                        help='Require this API-reported build before proceeding (e.g. 98310)')
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('--timeout must be finite and positive')
    if args.attach_port is not None and not 1 <= args.attach_port <= 65535:
        parser.error('--attach-port must be between 1 and 65535')
    if args.expected_base_build is not None and args.expected_base_build <= 0:
        parser.error('--expected-base-build must be positive')
    if args.output.exists():
        parser.error('Use a new --output file; previous probe evidence is preserved')
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    report = {"tested_at_utc": datetime.now(timezone.utc).isoformat(), "cases": [],
              "scope": "Ping only; no process launch, CreateGame, JoinGame, LeaveGame or Quit" if args.attach_port
                       else "CreateGame requests only; no JoinGame, policy or gameplay validation",
              "multiplayer_gameplay_confirmed": False}
    if args.expected_base_build is not None:
        report['expected_base_build'] = args.expected_base_build
    code = 0
    try:
        if args.attach_port is not None:
            asyncio.run(probe_connection(args.attach_port, args.timeout, report, args.expected_base_build))
            return 0
        report['installation'] = detect_installation()
        if not report['installation']['ready']:
            raise RuntimeError('SC2 installation checks failed: ' + '; '.join(report['installation']['errors']))
        map_path = maps.get(args.map).path
        report['map_sha256'] = hashlib.sha256(map_path.read_bytes()).hexdigest()
        # Bind upstream's lazy Paths to the discovered root (also for UTF-16
        # ExecuteInfo.txt files that the upstream parser cannot read).
        previous_root = os.environ.get('SC2PATH')
        try:
            if report['installation'].get('root'):
                os.environ['SC2PATH'] = report['installation']['root']
            kwargs = {} if args.expected_base_build is None else {'expected_base_build': args.expected_base_build}
            asyncio.run(probe(map_path, args.timeout, report, **kwargs))
        finally:
            if previous_root is None:
                os.environ.pop('SC2PATH', None)
            else:
                os.environ['SC2PATH'] = previous_root
    except Exception as exc:
        report["probe_error"] = f"{type(exc).__name__}: {exc}"
        code = 1
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as output:
            output.write(json.dumps(report, indent=2) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
