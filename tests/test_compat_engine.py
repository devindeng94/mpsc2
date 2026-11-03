import hashlib
import io
import json
import os
from pathlib import Path
import struct
from unittest.mock import Mock
import zlib

import pytest

from mpsc2 import compat_engine as compat
from mpsc2.cli import main


def blte(content=b'fixture engine', compressed=True):
    frame = b'Z' + zlib.compress(content) if compressed else b'N' + content
    header = b'BLTE' + struct.pack('>I', 36) + b'\x0f\x00\x00\x01'
    header += struct.pack('>II', len(frame), len(content)) + hashlib.md5(frame).digest()
    return header + frame, hashlib.md5(header).hexdigest()


@pytest.mark.parametrize('compressed', [True, False])
def test_blte_decodes_verified_frames(compressed):
    data, key = blte(compressed=compressed)
    assert compat._decode_blte(data, encoding_key=key, expected_size=14) == b'fixture engine'


@pytest.mark.parametrize('damage', ['header', 'frame', 'size', 'trailing', 'truncated'])
def test_blte_rejects_corrupt_or_unbounded_content(damage):
    data, key = blte()
    size = 14
    if damage == 'header':
        data = data[:13] + bytes([data[13] ^ 1]) + data[14:]
    elif damage == 'frame':
        data = data[:-1] + bytes([data[-1] ^ 1])
    elif damage == 'size':
        size = 1
    elif damage == 'trailing':
        data += b'extra'
    else:
        data = data[:-5]
    with pytest.raises(ValueError):
        compat._decode_blte(data, encoding_key=key, expected_size=size)


def test_bundle_manifest_has_only_unique_relative_app_paths():
    files = compat._bundle_manifest()['files']
    assert len(files) == 129
    assert sum(x['path'] == 'Contents/MacOS/SC2' for x in files) == 1


def download_fixture(monkeypatch, *, archive=False, status=None, content_range=None):
    data, key = blte()
    item = {'path': 'Contents/MacOS/SC2', 'size': 14,
            'sha256': hashlib.sha256(b'fixture engine').hexdigest(),
            'download': {'encoding_key': key, 'encoded_size': len(data)}}
    if archive:
        item['download']['archive'] = {'key': 'a' * 32, 'offset': 123, 'size': len(data)}
    class Response(io.BytesIO):
        def geturl(self):
            return self.url
    response = Response(data)
    response.status = status or (206 if archive else 200)
    response.headers = {'Content-Range': content_range or f'bytes 123-{122 + len(data)}/10000'}
    def respond(request, timeout):
        response.url = request.full_url
        return response
    request = Mock(side_effect=respond)
    monkeypatch.setattr(compat, 'urlopen', request)
    return item, key, request


@pytest.mark.parametrize('archive', [False, True])
def test_download_is_verified_then_reused_without_network(tmp_path, monkeypatch, archive):
    item, key, request = download_fixture(monkeypatch, archive=archive)
    assert compat._download_file(item, tmp_path) == b'fixture engine'
    assert (tmp_path / (key + '.blte')).is_file()
    assert compat._download_file(item, tmp_path) == b'fixture engine'
    request.assert_called_once()
    if archive:
        assert request.call_args.args[0].headers['Range'].startswith('bytes=123-')


@pytest.mark.parametrize('status,content_range', [(200, None), (206, 'bytes 0-10/10000')])
def test_archive_server_must_honor_exact_range(tmp_path, monkeypatch, status, content_range):
    item, _, _ = download_fixture(monkeypatch, archive=True, status=status, content_range=content_range)
    with pytest.raises(ValueError, match='requested archive range'):
        compat._download_file(item, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_untrusted_file_never_becomes_a_cache_entry(tmp_path, monkeypatch):
    item, _, _ = download_fixture(monkeypatch)
    item['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='does not match'):
        compat._download_file(item, tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.fixture
def retail(tmp_path, monkeypatch):
    if os.name == 'nt':
        pytest.skip('Mac compatibility-root preparation uses POSIX directory symlinks')
    monkeypatch.setattr(compat.platform, 'system', lambda: 'Darwin')
    source = tmp_path / 'retail'
    (source / 'SC2Data').mkdir(parents=True)
    (source / 'Maps').mkdir()
    (source / 'SC2Data/data').mkdir()
    (source / 'SC2Data/data/test').write_bytes(b'cached game data')
    (source / '.build.info').write_text('Active!DEC:1|Build Key!HEX:16|Version!STRING:0|Tags!STRING:0\n1|retail-key|5.0.17.98310|enUS\n')
    files = []
    for name, data in [('Contents/MacOS/SC2', b'retail engine'), ('Contents/Resources/test.txt', b'retail resource')]:
        path = source / 'Versions/Base98310/SC2.app' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        recovered = b'verified older engine' if name.endswith('/SC2') else data
        item = {'path': name, 'size': len(recovered), 'sha256': hashlib.sha256(recovered).hexdigest(),
                'source_size': len(data), 'source_md5': hashlib.md5(data).hexdigest()}
        if name.endswith('/SC2'):
            item['download'] = {}
        files.append(item)
    monkeypatch.setattr(compat, 'SOURCE_SHA256', hashlib.sha256(b'retail engine').hexdigest())
    monkeypatch.setattr(compat, '_bundle_manifest', lambda: {'files': files, 'build_config': {'text': 'fixture config'}})
    monkeypatch.setattr(compat, '_download_file', Mock(return_value=b'verified older engine'))
    return source


def test_prepare_preserves_retail_and_requires_explicit_selection(tmp_path, retail, monkeypatch):
    monkeypatch.setenv('SC2PATH', str(retail))
    target = tmp_path / 'separate engine'
    receipt = compat.prepare_macos_compat(retail, target)
    assert (retail / 'Versions/Base98310/SC2.app/Contents/MacOS/SC2').read_bytes() == b'retail engine'
    assert (target / 'Versions/Base96883/SC2.app/Contents/MacOS/SC2').read_bytes() == b'verified older engine'
    assert not (target / 'SC2Data').is_symlink()
    assert (target / 'SC2Data/data').resolve() == retail / 'SC2Data/data'
    assert (target / 'SC2Data/config/27/5c' / compat.BUILD_CONFIG_KEY).read_text() == 'fixture config'
    assert not (retail / 'SC2Data/config').exists()
    assert '5.0.15.96883|enUS' in (target / '.build.info').read_text()
    assert '5.0.17.98310|enUS' in (retail / '.build.info').read_text()
    assert not (target / '.build.info').is_symlink()
    assert receipt['engine_build'] == 96883 and receipt['source_build'] == 98310
    assert receipt['native_base98310_support'] is False
    assert json.loads((target / compat.RECEIPT_NAME).read_text()) == receipt
    assert os.environ['SC2PATH'] == str(retail)
    with pytest.raises(FileExistsError):
        compat.prepare_macos_compat(retail, target)


@pytest.mark.parametrize('location', ['destination', 'cache'])
def test_preparation_refuses_writes_inside_retail(tmp_path, retail, location):
    destination = retail / 'new' if location == 'destination' else tmp_path / 'new'
    cache = retail / 'cache' if location == 'cache' else tmp_path / 'cache'
    with pytest.raises(ValueError, match='outside the retail'):
        compat.prepare_macos_compat(retail, destination, cache=cache)
    assert not destination.exists() and not cache.exists()
    compat._download_file.assert_not_called()


def test_modified_source_resources_are_refused_before_download(tmp_path, retail):
    (retail / 'Versions/Base98310/SC2.app/Contents/Resources/test.txt').write_bytes(b'changed')
    with pytest.raises(ValueError, match='Unsupported source bundle resource'):
        compat.prepare_macos_compat(retail, tmp_path / 'new')
    compat._download_file.assert_not_called()
    assert not (tmp_path / 'new').exists()


def test_failed_preparation_removes_staging_and_keeps_retail(tmp_path, retail, monkeypatch):
    monkeypatch.setattr(compat.shutil, 'copyfile', Mock(side_effect=OSError('copy failed')))
    with pytest.raises(OSError, match='copy failed'):
        compat.prepare_macos_compat(retail, tmp_path / 'new')
    assert not (tmp_path / 'new').exists()
    assert not list(tmp_path.glob('.mpsc2-prepare-*'))
    assert (retail / 'SC2Data').is_dir()


def test_cli_exposes_explicit_compatibility_setup(tmp_path, retail, capsys):
    assert main(['prepare-macos-compat', '--installation', str(retail), '--destination', str(tmp_path / 'new')]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt['select_with']['SC2PATH'] == str(tmp_path / 'new')
    assert main(['prepare-macos-compat', '--installation', str(retail), '--destination', str(tmp_path / 'new')]) == 1


@pytest.mark.parametrize('text', ['', 'Active|Version\n1|5.0.17.98310\n',
    'Active|Build Key|Version\n0|key|5.0.17.98310\n',
    'Active|Build Key|Version\n1|key|5.0.16.97671\n',
    'Active|Build Key|Version\n1|key|5.0.17.98310\n1|key|5.0.17.98310\n'])
def test_wrong_or_ambiguous_build_metadata_is_refused(text):
    with pytest.raises(ValueError):
        compat._select_build_info(text)


def test_build_selection_preserves_other_fields_and_inactive_rows():
    original = 'Active|Build Key|Version|Tags\n1|old|5.0.17.98310|enUS\n0|ptr|future|ptr-tag\n'
    selected = compat._select_build_info(original)
    assert f'1|{compat.BUILD_CONFIG_KEY}|5.0.15.96883|enUS' in selected
    assert '0|ptr|future|ptr-tag' in selected


def test_cache_cannot_create_destination_during_preparation(tmp_path, retail):
    target = tmp_path / 'new'
    with pytest.raises(ValueError, match='outside the new'):
        compat.prepare_macos_compat(retail, target, cache=target / 'cache')
    assert not target.exists()


def test_non_mac_setup_is_refused_before_filesystem_work(tmp_path, monkeypatch):
    monkeypatch.setattr(compat.platform, 'system', lambda: 'Linux')
    with pytest.raises(RuntimeError, match='macOS only'):
        compat.prepare_macos_compat(tmp_path / 'absent', tmp_path / 'new')
    assert list(tmp_path.iterdir()) == []
