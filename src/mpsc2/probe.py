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

from loguru import logger
from s2clientprotocol import sc2api_pb2 as sc_pb
from sc2.data import Race

from .session import OwnedSC2Process, barrier
from . import maps
from .installation import detect_installation


async def probe(map_path, timeout, report):
    process = OwnedSC2Process(fullscreen=False, resolution=(640, 480))

    async def run_cases():
        async with process as controller:
            ping = (await barrier([controller.ping()], timeout, [controller]))[0].ping
            report["sc2"] = {"game_version": ping.game_version, "base_build": ping.base_build,
                             "data_version": ping.data_version}
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
    except asyncio.TimeoutError as exc:
        # asyncio.TimeoutError became an alias of the builtin only in 3.11.
        raise TimeoutError() from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", default="MPSC2TeamArena", help="Bundled name or path to a four-slot SC2Map")
    parser.add_argument("--output", type=Path, default=Path("reports/engine-capabilities.json"))
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('--timeout must be finite and positive')
    if args.output.exists():
        parser.error('Use a new --output file; previous probe evidence is preserved')
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    report = {"tested_at_utc": datetime.now(timezone.utc).isoformat(), "cases": [],
              "scope": "CreateGame requests only; no JoinGame, policy or gameplay validation",
              "multiplayer_gameplay_confirmed": False, "installation": detect_installation()}
    code = 0
    try:
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
            asyncio.run(probe(map_path, args.timeout, report))
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
