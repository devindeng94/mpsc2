"""Run unchanged example MacroBot policies through the multiplayer service."""
import argparse
import asyncio
import json
from pathlib import Path
from sc2.data import Race
from sc2.player import Bot
from mpsc2 import maps
from mpsc2.service import Installation, NativeFactory, LocalServer, ControlClient, match_spec, play_botais
from full_game import MacroBot


async def demo(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = maps.get('MPSC2Melee').path
    factory = NativeFactory({'selected': Installation(args.sc2_path.resolve(), args.sc2_version)},
                            {'melee': source}, output / 'matches')
    spec = match_spec('selected', 'melee', source, args.teams, realtime=args.realtime, joint_turns=False,
                      step_count=16, game_time_limit=args.game_time_limit)
    async with LocalServer(factory) as server, ControlClient(server.url, server.controller_token) as control:
        results = await play_botais(control, spec, [Bot(Race.Terran, MacroBot(output)) for _ in args.teams],
                                   save_replay_as=output / 'game.SC2Replay')
        snapshot = next(iter(server.coordinator.matches.values())).snapshot()
        report = {'results': [r.name for r in results], 'terminated': snapshot.terminated,
                  'truncated': snapshot.truncated, 'teams': args.teams, 'realtime': args.realtime}
        (output / 'service-result.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sc2-path', type=Path, required=True)
    parser.add_argument('--sc2-version', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--teams', type=int, nargs='+', default=[0,0,1,1])
    parser.add_argument('--realtime', action='store_true')
    parser.add_argument('--game-time-limit', type=float, default=600)
    asyncio.run(demo(parser.parse_args()))


if __name__ == '__main__':
    main()
