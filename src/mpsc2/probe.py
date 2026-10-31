"""Probe the installed engine's CreateGame limits without assuming client support."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

from loguru import logger
from s2clientprotocol import sc2api_pb2 as sc_pb
from sc2.data import Race

from .session import OwnedSC2Process, barrier


async def probe(map_path, timeout, report):
    process = OwnedSC2Process(fullscreen=False, resolution=(640, 480))

    async def run_cases():
        async with process as controller:
            ping = (await barrier([controller.ping()], timeout, [controller]))[0].ping
            report["sc2"] = {"game_version": ping.game_version, "base_build": ping.base_build,
                             "data_version": ping.data_version}
            for api_players, realtime in [(4, False), (4, True), (2, False), (1, False)]:
                request = sc_pb.RequestCreateGame(
                    local_map=sc_pb.LocalMap(map_path=str(map_path.resolve()), map_data=map_path.read_bytes()),
                    realtime=realtime, random_seed=1,
                )
                for _ in range(api_players):
                    request.player_setup.add(type=sc_pb.Participant)
                for _ in range(4 - api_players):
                    request.player_setup.add(type=sc_pb.Computer, race=Race.Terran.value, difficulty=sc_pb.VeryEasy)
                response = (await barrier([controller._execute(create_game=request)], timeout, [controller]))[0]
                has_error = response.create_game.HasField("error")
                entry = {"api_players": api_players, "computer_players": 4 - api_players,
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", type=Path, default=Path("maps/MPSC2TeamArena.SC2Map"))
    parser.add_argument("--output", type=Path, default=Path("reports/engine-capabilities.json"))
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    report = {"tested_at_utc": datetime.now(timezone.utc).isoformat(), "cases": [],
              "map_sha256": hashlib.sha256(args.map.read_bytes()).hexdigest()}
    code = 0
    try:
        asyncio.run(probe(args.map, args.timeout, report))
    except Exception as exc:
        report["probe_error"] = f"{type(exc).__name__}: {exc}"
        code = 1
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
