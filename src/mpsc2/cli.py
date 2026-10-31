"""Command-line diagnostics and replay viewer."""
import argparse
import json

from . import __version__, maps
from .capabilities import get_capabilities
from .replay import run_replay


def main(argv=None):
    parser = argparse.ArgumentParser(prog='mpsc2', description=__doc__)
    parser.add_argument('--version', action='version', version=f'mpsc2 {__version__}')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('doctor', help='Check multiplayer prerequisites without starting SC2')
    commands.add_parser('maps', help='List the installed multiplayer map paths')
    replay = commands.add_parser('replay', help='Watch a replay with python-sc2')
    replay.add_argument('path')
    replay.add_argument('--observed-id', type=int, default=0, help='Native player ID, or 0 for all-player view')
    replay.add_argument('--speed', type=float, default=1.0)
    replay.add_argument('--fast', action='store_true', help='Unpaced analysis instead of wall-clock playback')
    replay.add_argument('--step-size', type=int, default=4)
    replay.add_argument('--max-game-loop', type=int, help='Stop after a bounded preview')
    args = parser.parse_args(argv)
    if args.command == 'doctor':
        capabilities = get_capabilities()
        print(json.dumps(capabilities, indent=2))
        return 0 if capabilities['multiplayer']['ready'] else 1
    if args.command == 'maps':
        for name in maps.available():
            print(f'{name}: {maps.get(name).path}')
        return 0
    results = run_replay(None, args.path, realtime=not args.fast, observed_id=args.observed_id,
                         speed=args.speed, step_size=args.step_size, max_game_loop=args.max_game_loop)
    print(json.dumps({pid: result.name for pid, result in results.items()}))
    return 0
