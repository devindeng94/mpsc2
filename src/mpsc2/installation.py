"""Read-only installation discovery using the pinned python-sc2 conventions."""
from __future__ import annotations

import hashlib
import json
import locale
import os
from pathlib import Path
import re

from sc2 import paths as upstream

from .versions import MACOS_96883, compatibility_catalog


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def user_install(target: str) -> str | None:
    """Read Blizzard's last-launch location, including UTF-8/UTF-16 paths."""
    relative = upstream.USERPATH.get(target)
    if not relative:
        return None
    path = upstream.get_home() / Path(relative.replace('\\', '/'))
    if not path.is_file():
        return None
    data = path.read_bytes()
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        content = data.decode('utf-16')
    else:
        try:
            content = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            content = data.decode(locale.getpreferredencoding(False))
    match = re.search(r'^\s*executable\s*=\s*"?(.+?)[\\/]Versions[\\/]', content, re.MULTILINE | re.IGNORECASE)
    if not match:
        raise ValueError(f'No executable path in {path}')
    base = match.group(1)
    if target in {'WSL1', 'WSL2'}:
        base = str(upstream.wsl.win_path_to_wsl_path(base))
    return base if Path(base).is_dir() else None


def detect_installation() -> dict:
    """Inspect paths without initializing upstream's exit-on-error ``Paths``.

    Use the same SC2PF/SC2PATH, ExecuteInfo.txt and default-path precedence as
    burnysc2. A bad explicit SC2PATH is reported, never silently replaced.
    """
    target = upstream.platform_detect()
    errors, warnings = [], []
    checks = {'supported_platform': target in upstream.BASEDIR,
              'installation_directory': False, 'versions_directory': False,
              'executable_present': False, 'build_supported': False,
              'working_directory': False}
    report = {'platform': target, 'source': None, 'root': None, 'build': None,
              'installed_builds': [], 'build_directories': [], 'incomplete_builds': [],
              'executable': None, 'executable_sha256': None,
              'compatibility_observations': [],
              'compatibility_engine': None,
              'working_directory': None, 'checks': checks, 'errors': errors,
              'warnings': warnings, 'ready': False}
    if not checks['supported_platform']:
        errors.append(f'Unsupported SC2 platform: {target}. Check SC2PF if it is set.')
        return report

    base = os.environ.get('SC2PATH')
    source = 'SC2PATH'
    if not base:
        try:
            # This helper does not initialize Paths or start a process.
            base = user_install(target)
        except (OSError, ValueError, AttributeError, KeyError) as exc:
            warnings.append(f'Could not read upstream ExecuteInfo.txt: {exc}; set SC2PATH explicitly.')
        source = 'ExecuteInfo.txt' if base else 'platform default'
        base = base or upstream.BASEDIR[target]
    root = Path(base).expanduser().resolve()
    report.update(root=str(root), source=source)
    versions = root / 'Versions'
    cwd = root / upstream.CWD[target] if upstream.CWD[target] else None
    report['working_directory'] = str(cwd) if cwd else None
    try:
        checks['installation_directory'] = root.is_dir()
        checks['versions_directory'] = versions.is_dir()
        checks['working_directory'] = cwd is None or cwd.is_dir()
        if target == 'Linux' and (root / 'Maps').is_dir():
            missing = [p.name for p in (root / 'Maps').iterdir()
                       if (p.is_dir() or p.suffix.lower() == '.sc2map') and not (root / 'maps' / p.name).exists()]
            if missing:
                warnings.append('Linux SC2 guests resolve installed maps under lowercase maps/. '
                                'These entries exist only under Maps/: ' + ', '.join(sorted(missing)) +
                                '. Add corresponding links under maps/ without replacing existing content.')
        builds = sorted(int(p.name[4:]) for p in versions.iterdir()
                        if p.is_dir() and re.fullmatch(r'Base\d+', p.name)) if versions.is_dir() else []
        report['build_directories'] = builds
        report['installed_builds'] = [build for build in builds
            if (versions / f'Base{build}' / upstream.BINPATH[target]).is_file()]
        report['incomplete_builds'] = [build for build in builds if build not in report['installed_builds']]
        if report['incomplete_builds']:
            warnings.append(f'Build directories without an executable: {report["incomplete_builds"]}')
        if builds:
            build = builds[-1]
            executable = versions / f'Base{build}' / upstream.BINPATH[target]
            report.update(build=build, executable=str(executable))
            checks['build_supported'] = build >= 55958  # burnysc2's minimum API build
            checks['executable_present'] = executable.is_file()
            if checks['executable_present']:
                report['executable_sha256'] = file_sha256(executable)
                report['compatibility_observations'] = [
                    observation for observation in compatibility_catalog()['observations']
                    if observation.get('system') == target and observation.get('build') == build
                    and observation.get('executable_sha256') == report['executable_sha256']
                ]
                warnings.extend(o['note'] for o in report['compatibility_observations'] if o.get('note'))
                receipt_path = root / 'mpsc2-compat-engine.json'
                if receipt_path.is_file():
                    try:
                        if receipt_path.stat().st_size > 65536:
                            raise ValueError('receipt is too large')
                        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
                        if (not isinstance(receipt, dict) or receipt.get('format') != 1
                                or receipt.get('profile') != MACOS_96883.id or target != 'Darwin'
                                or build != MACOS_96883.build
                                or report['executable_sha256'] != MACOS_96883.executable_sha256):
                            raise ValueError('receipt does not match the selected engine')
                        report['compatibility_engine'] = {
                            'engine_build': build, 'source_build': receipt.get('source_build'),
                            'source_root': receipt.get('source_root'),
                            'content_selection': receipt.get('content_selection'),
                            'selected_data_version': receipt.get('data_version'),
                            'native_base98310_support': False,
                        }
                        warnings.append('Using the separate Base96883 API compatibility engine. '
                                        'Its signed app and data selection are pinned to 5.0.15, using the installed content cache; '
                                        'the Base98310 executable is not used.')
                        if file_sha256(root / '.build.info') != receipt.get('build_info_sha256'):
                            warnings.append('Compatibility game-data metadata changed after preparation; rerun live validation.')
                    except (OSError, ValueError, TypeError) as exc:
                        warnings.append(f'Cannot verify compatibility-engine receipt: {exc}')
        if not checks['installation_directory']:
            errors.append(f'SC2 installation directory not found: {root}. Set SC2PATH to the folder containing Versions.')
        elif not builds:
            errors.append(f'No Base<number> builds found in {versions}. Finish installing SC2 or correct SC2PATH.')
        elif not checks['executable_present']:
            errors.append(f'SC2 executable not found: {report["executable"]}. Finish installing this build.')
        if builds and not checks['build_supported']:
            errors.append('burnysc2 requires SC2 Base55958 (3.16.1) or newer.')
        if not checks['working_directory']:
            errors.append(f'SC2 working directory not found: {cwd}. A complete installation is required.')
    except OSError as exc:
        errors.append(f'Cannot inspect SC2 installation: {exc}')
    report['ready'] = all(checks.values()) and not errors
    return report
