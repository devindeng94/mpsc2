"""Run independent policies through protocol 1.0 against an explicit installation.

Example: python examples/service_joint_turns.py --sc2-path /path/to/StarCraftII \
  --sc2-version 5.0.15.96883 --output reports/service-demo --teams 0 0 1 1
"""
import argparse
import asyncio
from contextlib import AsyncExitStack
import json
import math
from pathlib import Path
from google.protobuf.json_format import MessageToDict
from s2clientprotocol import sc2api_pb2 as api
from mpsc2 import maps
from mpsc2.service import (Installation, NativeFactory, LocalServer, ControlClient,
                           TurnClient, match_spec)


async def demo(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = maps.get('MPSC2TeamArena').path
    factory = NativeFactory({'selected': Installation(args.sc2_path.resolve(), args.sc2_version)}, {'arena': source}, output / 'matches')
    spec = match_spec('selected', 'arena', source, args.teams, game_time_limit=args.game_time_limit,
                      round_timeout_ms=60000, step_count=8)
    report = {'scope': 'real engine through service joint turns', 'teams': args.teams, 'passed': False}
    async with LocalServer(factory) as server, ControlClient(server.url, server.controller_token) as control:
        prepared = None
        try:
            prepared = await control.prepare(spec)
            report['engine'] = MessageToDict(prepared.engine, preserving_proto_field_name=True)
            report['materialized_map'] = MessageToDict(prepared.materialized_map, preserving_proto_field_name=True)
            started = await control.start(prepared)
            report['start'] = MessageToDict(started, preserving_proto_field_name=True)
            report['loops'] = [started.game_loop]
            async with AsyncExitStack() as stack:
                clients = [await stack.enter_async_context(TurnClient(prepared, p.slot_id)) for p in prepared.players]
                moves = []
                if args.move:
                    for client in clients:
                        catalog = await client.read(api.Request(data=api.RequestData(ability_id=True)))
                        candidates = [a for a in catalog.data.abilities if a.link_name.casefold() == 'move' and a.button_name.casefold() == 'move']
                        if len(candidates) != 1:
                            raise RuntimeError('Runtime catalog does not uniquely identify Move')
                        observed = (await client.read(api.Request(observation=api.RequestObservation()))).observation.observation
                        unit = next(u for u in observed.raw_data.units if u.owner == observed.player_common.player_id)
                        actions = api.RequestAction()
                        command = actions.actions.add().action_raw.unit_command
                        command.ability_id = candidates[0].ability_id
                        command.unit_tags.append(unit.tag)
                        command.target_world_space_pos.x, command.target_world_space_pos.y = unit.pos.x + 4, unit.pos.y
                        moves.append((actions, unit.tag, unit.pos.x, unit.pos.y))
                    report['maximum_movement'] = [0.0] * len(clients)
                    report['first_action_results'] = []
                loop, epoch = started.game_loop, 0
                while True:
                    # Explicit no-op policies: choose every action before dispatch.
                    for index, client in enumerate(clients):
                        await client.submit(epoch, loop, moves[index][0] if moves and epoch == 0 else None)
                    results = await asyncio.gather(*(c.result(epoch) for c in clients))
                    report['loops'].append([r.game_loop for r in results])
                    if moves:
                        if epoch == 0:
                            report['first_action_results'] = [list(r.action_result.result) for r in results]
                            if any(list(r.action_result.result) != [1] for r in results):
                                raise RuntimeError('Engine rejected a movement action')
                        for index, (result, (_, tag, x, y)) in enumerate(zip(results, moves)):
                            unit = next((u for u in result.observation.observation.raw_data.units if u.tag == tag), None)
                            if unit:
                                report['maximum_movement'][index] = max(report['maximum_movement'][index], math.hypot(unit.pos.x-x, unit.pos.y-y))
                    if all(r.terminated for r in results):
                        break
                    loop, epoch = results[0].game_loop, epoch + 1
                    if epoch > 10000:
                        raise RuntimeError('Game did not terminate within the example round budget')
                report['end'] = MessageToDict(await control.get(prepared), preserving_proto_field_name=True)
                if moves and any(distance < 1 for distance in report['maximum_movement']):
                    raise RuntimeError('A movement action did not move its own unit')
                report['passed'] = True
                # Close before disconnecting player sockets.
                await control.close_match(prepared)
        except BaseException as exc:
            report['error'] = f'{type(exc).__name__}: {exc}'
            raise
        finally:
            if prepared:
                report['closed'] = MessageToDict(await control.close_match(prepared), preserving_proto_field_name=True)
            (output / 'service-result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': report['passed'], 'report': str(output / 'service-result.json')}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sc2-path', type=Path, required=True)
    parser.add_argument('--sc2-version', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--teams', type=int, nargs='+', default=[0,0,1,1])
    parser.add_argument('--game-time-limit', type=float, default=10)
    parser.add_argument('--move', action='store_true', help='Choose a Move ability from each runtime catalog and verify actual unit movement')
    asyncio.run(demo(parser.parse_args()))


if __name__ == '__main__':
    main()
