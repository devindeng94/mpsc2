"""Command-line diagnostics and replay viewer."""
import argparse
import json
from pathlib import Path

from . import __version__, maps
from .capabilities import get_capabilities
from .replay import run_replay


def main(argv=None):
    parser = argparse.ArgumentParser(prog='mpsc2', description=__doc__)
    parser.add_argument('--version', action='version', version=f'mpsc2 {__version__}')
    commands = parser.add_subparsers(dest='command', required=True)
    doctor = commands.add_parser('doctor', help='Detect the local SC2 installation and check backend prerequisites')
    doctor.add_argument('--mode', choices=('multiplayer', 'standard'), default='multiplayer',
                        help='Readiness used for the exit code (default: multiplayer); both reports are always included')
    doctor.add_argument('--output', type=Path, help='Save UTF-8 JSON diagnostics to a new file')
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
        capabilities['mode'] = args.mode
        capabilities['ready'] = capabilities[args.mode]['ready']
        text = json.dumps(capabilities, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open('x', encoding='utf-8') as output:
                output.write(text + '\n')
        print(text)
        return 0 if capabilities['ready'] else 1
    if args.command == 'maps':
        for name in maps.available():
            print(f'{name}: {maps.get(name).path}')
        return 0
    results = run_replay(None, args.path, realtime=not args.fast, observed_id=args.observed_id,
                         speed=args.speed, step_size=args.step_size, max_game_loop=args.max_game_loop)
    print(json.dumps({pid: result.name for pid, result in results.items()}))
    return 0
