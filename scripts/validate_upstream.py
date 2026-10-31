"""Run python-sc2's offline tests through mpsc2 imports against the pinned release.

Install .[dev], then supply an extracted upstream checkout at commit
0875b4bb953c96a3eea3cc12d1a57b9e208bd95f (burnysc2 7.3.0).
Only imports are adapted; assertions and game-data fixtures remain unchanged.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import mpsc2
import sc2

UPSTREAM_COMMIT = '0875b4bb953c96a3eea3cc12d1a57b9e208bd95f'
TESTS = ['test_pickled_data.py', 'test_pickled_ramp.py', 'test_directions.py', 'test_expiring_dict.py']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    installed = Path(sc2.__file__).parent
    compared = {}
    for path in (source/'sc2').rglob('*.py'):
        name = path.relative_to(source/'sc2')
        actual = installed/name
        if not actual.is_file() or actual.read_bytes() != path.read_bytes():
            raise ValueError(f'Upstream source does not match the installed pinned package: {name}')
        compared[str(name)] = hashlib.sha256(path.read_bytes()).hexdigest()
    if len(compared) < 40:
        raise ValueError('Missing upstream source files')
    output.mkdir(parents=True, exist_ok=False)
    adapted = output/'adapted'
    tests = adapted/'test'
    tests.mkdir(parents=True)
    (tests/'__init__.py').write_text('')
    shutil.copyfile(source/'LICENSE', adapted/'LICENSE.python-sc2')
    shutil.copytree(source/'test/pickle_data', tests/'pickle_data')
    for name in TESTS:
        original = (source/'test'/name).read_text()
        (tests/name).write_text(re.sub(r'(?m)^from sc2(?=\.)', 'from mpsc2', original))
    env = {**os.environ, 'PYTHONDONTWRITEBYTECODE':'1', 'SC2PATH':'/nonexistent/mpsc2',
           'PYTHONPATH':os.pathsep.join([str(Path(mpsc2.__file__).parent.parent),str(adapted)]),
           'HYPOTHESIS_STORAGE_DIRECTORY':str(output/'hypothesis')}
    command = [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '-c', os.devnull,
               '--rootdir', str(adapted), '--junitxml', str(output/'junit.xml'),
               *[str(tests/name) for name in TESTS]]
    with (output/'pytest.log').open('w') as log:
        run = subprocess.run(command, cwd=adapted, env=env, stdout=log, stderr=subprocess.STDOUT)
    summary = {'upstream_commit':UPSTREAM_COMMIT, 'compared_source_files':compared,
               'adaptation':'Only from sc2.X imports replaced with from mpsc2.X; original assertions and fixtures',
               'fixture_count':len(list((tests/'pickle_data').glob('*.xz'))),
               'returncode':run.returncode, 'passed':run.returncode == 0}
    if (output/'junit.xml').is_file():
        suites = ET.parse(output/'junit.xml').getroot().findall('testsuite')
        summary['tests'] = sum(int(s.attrib['tests']) for s in suites)
        summary['failures'] = sum(int(s.attrib['failures']) for s in suites)
        summary['errors'] = sum(int(s.attrib['errors']) for s in suites)
        summary['skipped'] = sum(int(s.attrib['skipped']) for s in suites)
    (output/'validation.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k != 'compared_source_files'},indent=2))
    raise SystemExit(run.returncode)


if __name__ == '__main__':
    main()
