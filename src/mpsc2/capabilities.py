"""Read-only platform, installation and backend capability checks."""
from importlib.metadata import version
from pathlib import Path
import platform
import shutil

from . import maps
from .arena import validate_map
from .native_session import BUILD, EXECUTABLE_SHA256
from .installation import detect_installation, file_sha256


def get_capabilities() -> dict:
    """Describe support and check local prerequisites, without launching SC2.

    ``ready`` means these static checks passed; a successful game is still the
    integration test for game data, graphics and local networking.
    """
    from . import __version__
    installation = detect_installation()
    supported = platform.system() == 'Darwin' and installation['platform'] == 'Darwin'
    root = Path(installation['root']) if installation['root'] else None
    executable = root / f'Versions/Base{BUILD}/SC2.app/Contents/MacOS/SC2' if supported and root else None
    checks = {'platform_supported': supported, 'executable_present': False,
              'executable_matches': False, 'bundled_maps': False}
    if supported:
        checks['clang'] = shutil.which('clang') is not None
    errors = []
    actual_hash = None
    if executable is not None:
        try:
            checks['executable_present'] = executable.is_file()
            if checks['executable_present']:
                actual_hash = file_sha256(executable)
                checks['executable_matches'] = actual_hash == EXECUTABLE_SHA256
        except OSError as exc:
            errors.append(str(exc))
    if not supported:
        errors.append(f'No native multiplayer backend for {installation["platform"]}. '
                      'Bundled 2–8-client scenarios still require the supported macOS build. '
                      'Use doctor --mode standard for upstream one/two-player games; '
                      'use python -m mpsc2.probe to measure the installed engine\'s CreateGame limits.')
    else:
        if not checks['executable_present']:
            errors.append(f'The native backend requires {executable}.')
        elif not checks['executable_matches']:
            errors.append('The native executable hash is unsupported; refusing build-specific memory changes.')
        if not checks['clang']:
            errors.append('The native backend requires Apple clang for 3–8 clients.')
    try:
        scenarios = {name: validate_map(maps.get(name).path) for name in maps.available()}
        checks['bundled_maps'] = True
    except (ValueError, OSError) as exc:
        scenarios = {}
        errors.append(str(exc))
    return {
        'mpsc2': __version__, 'python': platform.python_version(), 'platform': platform.platform(),
        'burnysc2': version('burnysc2'),
        'installation': installation,
        'standard_games': 'Delegated to burnysc2; requires its supported local SC2 installation',
        'standard': {'backend': 'burnysc2', 'ready': installation['ready'],
                     'checks': dict(installation['checks']), 'errors': list(installation['errors']),
                     'note': 'Static installation checks only; maps, graphics and actual gameplay still need a live test.'},
        'multiplayer': {
            'backend': 'experimental macOS native bridge' if supported else None,
            'supported': supported, 'build': BUILD if supported else None,
            'players': list(range(2, 9)) if supported else [],
            'player_types': ['Bot'] if supported else [], 'realtime': [False, True] if supported else [],
            'bridge_required_above': 2,
            'observation_guard': '3..8 clients: seven-byte process-private fix for Base96883 opponent-upgrade indexing' if supported else None,
            'maps': scenarios, 'team_layouts': 'Any partition into at least two teams, including FFA',
            'ready': all(checks.values()), 'checks': checks, 'errors': errors,
            'executable': str(executable) if executable else None, 'executable_sha256': actual_hash,
            'expected_sha256': EXECUTABLE_SHA256 if supported else None,
        },
    }


__all__ = ['get_capabilities']
