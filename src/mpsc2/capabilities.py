"""Read-only platform, installation and registered-backend capability checks."""
from importlib.metadata import version
from pathlib import Path
import platform
import shutil

from . import maps
from .arena import validate_map
from .installation import detect_installation, file_sha256
from .versions import get_native_profile, get_game_version, find_native_profile, UnsupportedNativeProfile


def get_capabilities(sc2_version=None) -> dict:
    """Check one native profile; static readiness is not a live gameplay test.

    The standard section describes the installation's default upstream route.
    An explicit sc2_version selects only the native profile checked here.
    """
    from . import __version__
    installation = detect_installation()
    system = platform.system()
    root = Path(installation['root']) if installation['root'] else None
    errors = []
    profile = None
    try:
        if system != installation['platform']:
            raise UnsupportedNativeProfile('Host and SC2 target platforms do not match')
        profile = get_native_profile(system, sc2_version)
    except UnsupportedNativeProfile as error:
        errors.append(str(error))
    windows = profile is not None and profile.system == 'Windows'
    executable = profile.executable(root) if profile and root else None
    checks = {'platform_supported': system in ('Windows', 'Darwin') and system == installation['platform'],
              'profile_available': profile is not None, 'executable_present': False,
              'executable_matches': False, 'bundled_maps': False}
    if windows:
        from .windows_session import compiler
        import struct
        import sysconfig
        checks['windows_compiler'] = compiler() is not None
        checks['python_64_bit'] = struct.calcsize('P') == 8
        checks['python_x86_64'] = sysconfig.get_platform().lower() == 'win-amd64'
        checks['working_directory'] = bool(root and (root / profile.working_directory).is_dir())
    elif profile:
        checks['clang'] = shutil.which('clang') is not None
    actual_hash = None
    if executable is not None:
        try:
            checks['executable_present'] = executable.is_file()
            if checks['executable_present']:
                actual_hash = file_sha256(executable)
                checks['executable_matches'] = actual_hash == profile.executable_sha256
        except OSError as error:
            errors.append(str(error))
    if profile:
        if not checks['executable_present']:
            errors.append(f'The native profile requires {executable or profile.executable_relative_path}.')
        elif not checks['executable_matches']:
            errors.append('The native executable hash is unsupported; refusing build-specific memory changes.')
        if windows and not checks['windows_compiler']:
            errors.append('Windows 3–8 clients require MinGW-w64 gcc; set MPSC2_WINDOWS_CC to gcc.exe.')
        elif not windows and not checks['clang']:
            errors.append('The native backend requires Apple clang for 3–8 clients.')
        if windows and not checks['python_64_bit']:
            errors.append('Windows multiplayer requires 64-bit Python.')
        elif windows and not checks['python_x86_64']:
            errors.append('The Windows x86_64 profile requires an x86_64 Windows Python interpreter.')
        if windows and not checks['working_directory']:
            errors.append('Windows multiplayer requires the installation Support64 directory.')
    try:
        scenarios = {name: validate_map(maps.get(name).path) for name in maps.available()}
        checks['bundled_maps'] = True
    except (ValueError, OSError) as error:
        scenarios = {}
        errors.append(str(error))
    game = get_game_version(sc2_version if sc2_version is not None else profile.game_version) if profile else None
    return {
        'mpsc2': __version__, 'python': platform.python_version(), 'platform': platform.platform(),
        'burnysc2': version('burnysc2'), 'installation': installation,
        'standard_games': 'Delegated to burnysc2; requires its supported local SC2 installation',
        'standard': {'backend': 'burnysc2', 'ready': installation['ready'],
                     'checks': dict(installation['checks']), 'errors': list(installation['errors']),
                     'note': 'Default installation only; a native sc2_version selection does not select the standard build.'},
        'multiplayer': {
            'backend': profile.backend if profile else None,
            'profile': profile.summary() if profile else None,
            'requested_version': sc2_version,
            'game_version': game.label if game else None,
            'data_version': game.data_version if game else None,
            'supported': profile is not None, 'build': str(profile.build) if profile else None,
            'players': list(profile.players) if profile else [],
            'player_types': ['Bot'] if profile else [], 'realtime': [False, True] if profile else [],
            'bridge_required_above': 2,
            'observation_guard': profile.observation_strategy if profile else None,
            'maps': scenarios, 'team_layouts': 'Any partition into at least two teams, including FFA',
            'ready': all(checks.values()) and not errors, 'checks': checks, 'errors': errors,
            'executable': str(executable) if executable else None, 'executable_sha256': actual_hash,
            'expected_sha256': profile.executable_sha256 if profile else None,
            'detected_builds': [
                {'build': build, 'executable_present': build in installation['installed_builds'],
                 'native_profile_available': find_native_profile(system, build) is not None}
                for build in installation.get('build_directories', installation['installed_builds'])
            ],
        },
    }


__all__ = ['get_capabilities']
