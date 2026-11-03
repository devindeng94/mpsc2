"""Real-engine service smoke matrix; requires an explicitly selected installation.

Runs 2..8 joint-turn clients, four-player FFA/3v1, and a short realtime
four-player BotAI game. Does not certify full economic play in every case.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sc2-path', type=Path, required=True)
    parser.add_argument('--sc2-version', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cases', nargs='+', help='Run selected named cases only')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    cases = [(f'joint-{n}', 'service_joint_turns.py', list(range(n)), []) for n in range(2,9)]
    cases.extend([('joint-4-3v1', 'service_joint_turns.py', [0,0,0,1], []),
                  ('joint-4-2v2', 'service_joint_turns.py', [0,0,1,1], []),
                  ('joint-4-move', 'service_joint_turns.py', [0,0,1,1], ['--move']),
                  ('realtime-4-2v2', 'service_botai.py', [0,0,1,1], ['--realtime'])])
    if args.cases:
        unknown = set(args.cases) - {c[0] for c in cases}
        if unknown:
            parser.error(f'Unknown cases: {sorted(unknown)}')
        cases = [c for c in cases if c[0] in args.cases]
    results = []
    for name, script, teams, extra in cases:
        print(f'Starting {name}', flush=True)
        command = [sys.executable, str(root / 'examples' / script), '--sc2-path', str(args.sc2_path.resolve()),
                   '--sc2-version', args.sc2_version, '--output', str(output / name),
                   '--teams', *map(str, teams), '--game-time-limit', '10', *extra]
        with (output / f'{name}.log').open('w') as log:
            result = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT, timeout=600)
        record = {'name': name, 'teams': teams, 'exit_code': result.returncode, 'passed': result.returncode == 0}
        results.append(record)
        (output / 'matrix.json').write_text(json.dumps({'cases': results, 'passed': all(r['passed'] for r in results)}, indent=2) + '\n')
        print(json.dumps(record), flush=True)
        if result.returncode:
            raise SystemExit(f'{name} failed; see {output / (name + ".log")}')


if __name__ == '__main__':
    main()
