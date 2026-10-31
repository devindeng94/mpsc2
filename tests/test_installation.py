import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from mpsc2.capabilities import get_capabilities
from mpsc2.cli import main
from mpsc2.installation import detect_installation, upstream
from mpsc2.native_session import NativeMultiplayerSession


def installation(tmp_path, monkeypatch, target='Windows', builds=(96883, 99999)):
    root = tmp_path / 'Games with spaces 游戏' / 'StarCraft II'
    for build in builds:
        executable = root / 'Versions' / f'Base{build}' / upstream.BINPATH[target]
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_bytes(b'fixture executable')
    if upstream.CWD[target]:
        (root / upstream.CWD[target]).mkdir()
    monkeypatch.setattr(upstream, 'PF', target)
    monkeypatch.setattr(upstream, 'platform_detect', lambda: target)
    monkeypatch.setenv('SC2PATH', str(root))
    return root


@pytest.mark.parametrize('target,binary', [('Windows', 'SC2_x64.exe'), ('Darwin', 'SC2'), ('Linux', 'SC2_x64')])
def test_detects_platform_executable_and_numeric_latest_build(tmp_path, monkeypatch, target, binary):
    root = installation(tmp_path, monkeypatch, target, (99999, 100000))
    (root / 'Versions' / 'BaseNotABuild').mkdir()
    with patch('subprocess.Popen', side_effect=AssertionError('doctor must not launch')):
        report = detect_installation()
    assert report['ready'] and not report['errors']
    assert report['source'] == 'SC2PATH'
    assert report['installed_builds'] == [99999, 100000]
    assert report['build'] == 100000
    assert Path(report['executable']).name == binary
    assert len(report['executable_sha256']) == 64


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-8-sig', 'utf-16'])
def test_windows_uses_executeinfo_for_custom_install(tmp_path, monkeypatch, encoding):
    root = installation(tmp_path, monkeypatch)
    monkeypatch.delenv('SC2PATH')
    home = tmp_path / 'home'
    info = home / 'Documents/StarCraft II/ExecuteInfo.txt'
    info.parent.mkdir(parents=True)
    # POSIX separators also work on Windows, and keep this fixture portable.
    monkeypatch.setitem(upstream.USERPATH, 'Windows', 'Documents/StarCraft II/ExecuteInfo.txt')
    monkeypatch.setattr(upstream, 'get_home', lambda: home)
    info.write_text(f'executable = "{root.as_posix()}/Versions/Base99999/SC2_x64.exe"', encoding=encoding)
    report = detect_installation()
    assert report['source'] == 'ExecuteInfo.txt'
    assert report['root'] == str(root.resolve())
    assert report['ready']


def test_native_doctor_still_checks_pinned_build_instead_of_latest(tmp_path, monkeypatch):
    root = installation(tmp_path, monkeypatch, 'Darwin')
    with patch('mpsc2.capabilities.platform.system', return_value='Darwin'), \
         patch('mpsc2.capabilities.shutil.which', return_value='/fixture/clang'):
        info = get_capabilities()
    assert info['installation']['build'] == 99999
    assert info['standard']['ready']
    assert info['multiplayer']['executable'] == str(root / 'Versions/Base96883/SC2.app/Contents/MacOS/SC2')
    assert info['multiplayer']['checks']['executable_present']
    assert not info['multiplayer']['checks']['executable_matches']
    assert not info['multiplayer']['ready']


def test_explicit_bad_path_is_not_replaced_by_detected_install(tmp_path, monkeypatch):
    root = installation(tmp_path, monkeypatch)
    monkeypatch.setenv('SC2PATH', str(tmp_path / 'missing'))
    with patch('mpsc2.installation.user_install', return_value=str(root)) as discover:
        report = detect_installation()
    discover.assert_not_called()
    assert not report['ready'] and report['executable'] is None
    assert report['source'] == 'SC2PATH'
    assert 'Set SC2PATH' in report['errors'][0]


def test_malformed_executeinfo_falls_back_with_warning(tmp_path, monkeypatch):
    root = installation(tmp_path, monkeypatch)
    monkeypatch.delenv('SC2PATH')
    monkeypatch.setitem(upstream.BASEDIR, 'Windows', str(root))
    with patch('mpsc2.installation.user_install', side_effect=ValueError('bad ExecuteInfo')):
        report = detect_installation()
    assert report['source'] == 'platform default' and report['ready']
    assert report['warnings']


@pytest.mark.parametrize('missing', ['executable', 'Support64'])
def test_incomplete_windows_installation_is_not_ready(tmp_path, monkeypatch, missing):
    root = installation(tmp_path, monkeypatch)
    if missing == 'executable':
        (root / 'Versions/Base99999/SC2_x64.exe').unlink()
    else:
        (root / 'Support64').rmdir()
    report = detect_installation()
    assert not report['ready'] and report['errors']
    assert report['build'] == 99999  # do not silently select an older build


def test_old_and_unknown_platforms_are_reported_without_exit(tmp_path, monkeypatch):
    installation(tmp_path, monkeypatch, builds=(55957,))
    assert not detect_installation()['ready']
    monkeypatch.setattr(upstream, 'platform_detect', lambda: 'UnknownOS')
    report = detect_installation()
    assert not report['ready'] and report['root'] is None and report['errors']


def test_unreadable_executable_is_reported(tmp_path, monkeypatch):
    installation(tmp_path, monkeypatch)
    with patch('mpsc2.installation.file_sha256', side_effect=PermissionError('denied')):
        report = detect_installation()
    assert not report['ready'] and 'denied' in report['errors'][0]


def test_windows_doctor_separates_standard_and_native_support(tmp_path, monkeypatch, capsys):
    installation(tmp_path, monkeypatch)
    with patch('mpsc2.capabilities.platform.system', return_value='Windows'):
        info = get_capabilities()
        assert main(['doctor', '--mode', 'standard', '--output', str(tmp_path / 'doctor.json')]) == 0
        assert main(['doctor']) == 1
    assert info['standard']['ready']
    native = info['multiplayer']
    assert not native['ready'] and not native['supported']
    assert native['executable'] is None and native['expected_sha256'] is None
    assert 'clang' not in native['checks']
    assert 'Windows' in native['errors'][0]
    saved = json.loads((tmp_path / 'doctor.json').read_text(encoding='utf-8'))
    assert saved['ready'] and saved['mode'] == 'standard'
    assert 'SC2.app' not in capsys.readouterr().out


def test_doctor_preserves_previous_report(tmp_path):
    output = tmp_path / 'doctor.json'
    output.write_text('prior evidence')
    with patch('mpsc2.cli.get_capabilities', return_value={'standard': {'ready': True}}):
        with pytest.raises(FileExistsError):
            main(['doctor', '--mode', 'standard', '--output', str(output)])
    assert output.read_text() == 'prior evidence'


def test_native_launch_on_windows_refuses_before_paths_or_helpers(tmp_path):
    source = tmp_path / 'map.SC2Map'
    source.write_bytes(b'map fixture')
    output = tmp_path / 'run'
    session = NativeMultiplayerSession(source, output=output)
    with patch('mpsc2.native_session.platform.system', return_value='Windows'), \
         patch('mpsc2.native_session.build_bridge') as compile_bridge, \
         patch('mpsc2.native_session.NativeProcess') as launch:
        with pytest.raises(RuntimeError, match='No native multiplayer backend for Windows'):
            asyncio.run(session.__aenter__())
    compile_bridge.assert_not_called()
    launch.assert_not_called()
    assert not output.exists()
