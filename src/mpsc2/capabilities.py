"""Read-only checks for the experimental multiplayer backend."""
import hashlib
from importlib.metadata import version
import os
from pathlib import Path
import platform
import shutil

from . import maps
from .arena import validate_map
from .native_session import BUILD, EXECUTABLE_SHA256


def get_capabilities() -> dict:
    """Describe support and check local prerequisites, without launching SC2.

    ``ready`` means these static checks passed; a successful game is still the
    integration test for game data, graphics and local networking.
    """
    root = Path(os.environ.get('SC2PATH', '/Applications/StarCraft II')).expanduser().resolve()
    executable = root / f'Versions/Base{BUILD}/SC2.app/Contents/MacOS/SC2'
    checks = {'macos': platform.system() == 'Darwin', 'clang': shutil.which('clang') is not None,
              'executable_present': executable.is_file(), 'executable_matches': False, 'bundled_maps': False}
    errors = []
    actual_hash = None
    if checks['executable_present']:
        try:
            actual_hash = hashlib.sha256(executable.read_bytes()).hexdigest()
            checks['executable_matches'] = actual_hash == EXECUTABLE_SHA256
        except OSError as exc:
            errors.append(str(exc))
    try:
        scenarios = {name: validate_map(maps.get(name).path) for name in maps.available()}
        checks['bundled_maps'] = True
    except (ValueError, OSError) as exc:
        scenarios = {}
        errors.append(str(exc))
    return {
        'python': platform.python_version(), 'platform': platform.platform(),
        'burnysc2': version('burnysc2'),
        'standard_games': 'Delegated to burnysc2; requires its supported local SC2 installation',
        'multiplayer': {
            'backend': 'experimental macOS native bridge', 'build': BUILD,
            'players': list(range(2, 9)), 'player_types': ['Bot'], 'realtime': [False, True],
            'bridge_required_above': 2,
            'observation_guard': '3..8 clients: seven-byte process-private fix for Base96883 opponent-upgrade indexing',
            'maps': scenarios, 'team_layouts': 'Any partition into at least two teams, including FFA',
            'ready': all(checks.values()), 'checks': checks, 'errors': errors,
            'executable': str(executable), 'executable_sha256': actual_hash,
            'expected_sha256': EXECUTABLE_SHA256,
        },
    }


__all__ = ['get_capabilities']
