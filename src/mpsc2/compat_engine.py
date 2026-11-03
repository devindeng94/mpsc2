"""Prepare an explicitly selected Mac research engine beside a retail install.

This restores the verified Base96883 app and data selection into a separate root.
It does not add an API to Base98310, replace retail files, or redistribute SC2.
All app files are verified against pinned Blizzard install-manifest metadata.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import struct
import tempfile
from urllib.request import Request, urlopen
import zlib

from .installation import file_sha256
from .versions import MACOS_96883


SOURCE_BUILD = 98310
SOURCE_SHA256 = 'cbe001a76f5962b207c71179ae86b6129561066d62bc59c0543186f43bfffeb1'
BUNDLE_MANIFEST_SHA256 = '341c624ae48c643ab50cd6ba999f99f429e2d244de61f9b1665bf562e7e0a3c3'
BUILD_CONFIG_KEY = '275c3e0594f089a29a5d7b1f470511a3'
DATA_VERSION = 'B49DA51995BA9767F4C624034C211342'
CDN = 'https://us.cdn.blizzard.com/tpr/sc2/data'
RECEIPT_NAME = 'mpsc2-compat-engine.json'


def _bundle_manifest():
    data = (Path(__file__).parent / 'assets/macos-96883-bundle.json').read_bytes()
    if hashlib.sha256(data).hexdigest() != BUNDLE_MANIFEST_SHA256:
        raise RuntimeError('Compatibility bundle manifest differs from the verified version')
    manifest = json.loads(data)
    files = manifest['files']
    seen = set()
    for item in files:
        path = PurePosixPath(item['path'])
        if (path.is_absolute() or '..' in path.parts or not path.parts
                or path.parts[0] != 'Contents' or str(path) != item['path'] or str(path) in seen):
            raise ValueError('Invalid compatibility bundle path')
        seen.add(str(path))
    config = manifest['build_config']
    if config['key'] != BUILD_CONFIG_KEY or hashlib.md5(config['text'].encode()).hexdigest() != BUILD_CONFIG_KEY:
        raise ValueError('Invalid compatibility build configuration')
    return manifest


def _decode_blte(blob: bytes, *, encoding_key: str, expected_size: int) -> bytes:
    """Decode a bounded Blizzard BLTE object; accept only raw/zlib frames."""
    if len(blob) < 9 or blob[:4] != b'BLTE':
        raise ValueError('Invalid BLTE header')
    header = int.from_bytes(blob[4:8], 'big')
    if header == 0:
        if hashlib.md5(blob).hexdigest() != encoding_key:
            raise ValueError('BLTE object checksum mismatch')
        frames = [(blob[8:], expected_size)]
    else:
        if header > len(blob) or header < 36 or blob[8] != 15:
            raise ValueError('Invalid BLTE frame table')
        count = int.from_bytes(blob[9:12], 'big')
        if count > 10000 or header != 12 + 24 * count:
            raise ValueError('Invalid BLTE frame count')
        if hashlib.md5(blob[:header]).hexdigest() != encoding_key:
            raise ValueError('BLTE header checksum mismatch')
        frames, offset, total = [], header, 0
        for i in range(count):
            compressed, expanded = struct.unpack_from('>II', blob, 12 + 24 * i)
            total += expanded
            if not compressed or total > expected_size or offset + compressed > len(blob):
                raise ValueError('BLTE frame exceeds expected size')
            frame = blob[offset:offset + compressed]
            if hashlib.md5(frame).digest() != blob[20 + 24 * i:36 + 24 * i]:
                raise ValueError('BLTE frame checksum mismatch')
            frames.append((frame, expanded))
            offset += compressed
        if offset != len(blob) or total != expected_size:
            raise ValueError('BLTE object size mismatch')
    output = bytearray()
    for frame, size in frames:
        if frame[:1] == b'N':
            content = frame[1:]
        elif frame[:1] == b'Z':
            decoder = zlib.decompressobj()
            try:
                content = decoder.decompress(frame[1:], size + 1)
            except zlib.error as exc:
                raise ValueError('Invalid BLTE compressed frame') from exc
            if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                raise ValueError('Invalid or oversized BLTE compressed frame')
        else:
            raise ValueError('Unsupported BLTE compression mode')
        if len(content) != size:
            raise ValueError('BLTE decoded size mismatch')
        output.extend(content)
    return bytes(output)


def _download_file(item: dict, cache: Path, progress=None) -> bytes:
    """Retrieve one pinned object, including bounded archive byte ranges."""
    spec = item['download']
    key, expected_size = spec['encoding_key'], spec['encoded_size']
    archive = spec.get('archive')
    remote_key = archive['key'] if archive else key
    url = f'{CDN}/{remote_key[:2]}/{remote_key[2:4]}/{remote_key}'
    headers = {}
    if archive:
        if archive['size'] != expected_size:
            raise ValueError('Invalid archive range size')
        end = archive['offset'] + expected_size - 1
        headers['Range'] = f'bytes={archive["offset"]}-{end}'

    def verify(path):
        if path.stat().st_size != expected_size:
            raise ValueError(f'Invalid cached object size; remove or move {path} before retrying')
        content = _decode_blte(path.read_bytes(), encoding_key=key, expected_size=item['size'])
        if hashlib.sha256(content).hexdigest() != item['sha256']:
            raise ValueError(f'Recovered file does not match the verified bundle: {item["path"]}')
        return content

    cache.mkdir(parents=True, exist_ok=True)
    target = cache / (key + '.blte')
    if not target.exists():
        if progress:
            progress(f'Downloading verified Base96883 file: {item["path"]} ({expected_size:,} bytes)')
        fd, temporary = tempfile.mkstemp(prefix='.download-', dir=cache)
        try:
            with os.fdopen(fd, 'wb') as output, urlopen(Request(url, headers=headers), timeout=60) as response:
                if response.geturl() != url:
                    raise ValueError('Unexpected compatibility download redirect')
                if archive:
                    expected_range = f'bytes {archive["offset"]}-{end}/'
                    if response.status != 206 or not response.headers.get('Content-Range', '').startswith(expected_range):
                        raise ValueError('Server did not honor the requested archive range')
                elif response.status != 200:
                    raise ValueError('Unexpected compatibility download response')
                size = 0
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > expected_size:
                        raise ValueError('Compatibility download exceeds the pinned size')
                    output.write(chunk)
            if size != expected_size:
                raise ValueError('Incomplete compatibility download')
            # Validate before publishing a reusable cache entry.
            content = verify(Path(temporary))
            os.replace(temporary, target)
            return content
        finally:
            Path(temporary).unlink(missing_ok=True)
    return verify(target)


def _select_build_info(text: str) -> str:
    """Change only the separate root's active build selection, preserving CDN/tags."""
    lines = text.splitlines()
    if not lines:
        raise ValueError('Missing retail build metadata')
    columns = [part.split('!', 1)[0] for part in lines[0].split('|')]
    try:
        active, build, version = (columns.index(name) for name in ('Active', 'Build Key', 'Version'))
    except ValueError as exc:
        raise ValueError('Unsupported retail build metadata columns') from exc
    changed = 0
    for index in range(1, len(lines)):
        fields = lines[index].split('|')
        if len(fields) != len(columns):
            raise ValueError('Invalid retail build metadata row')
        if fields[active] == '1':
            if fields[version] != '5.0.17.98310':
                raise ValueError('Expected active retail Base98310 metadata')
            fields[build], fields[version] = BUILD_CONFIG_KEY, '5.0.15.96883'
            lines[index] = '|'.join(fields)
            changed += 1
    if changed != 1:
        raise ValueError('Expected exactly one active retail build')
    return '\n'.join(lines) + '\n'


def prepare_macos_compat(installation, destination, *, cache=None, progress=None) -> dict:
    """Restore a separate, verified Base96883 app and matching data selection.

    Select the returned root explicitly via SC2PATH. Game data/support folders
    remain linked to the user's installation; build metadata is kept separately.
    An existing destination is always refused. No process is started here.
    """
    if platform.system() != 'Darwin':
        raise RuntimeError('This compatibility engine is for macOS only')
    source = Path(installation).expanduser().resolve()
    destination = Path(destination).expanduser().absolute()
    cache = (Path(cache).expanduser() if cache else destination.parent / '.mpsc2-downloads').resolve()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f'Use a new compatibility destination: {destination}')
    destination = destination.resolve()
    if source == destination or source in destination.parents or source == cache or source in cache.parents:
        raise ValueError('Compatibility files and cache must be outside the retail installation')
    if cache == destination or destination in cache.parents:
        raise ValueError('Download cache must be outside the new compatibility destination')
    bundle = source / f'Versions/Base{SOURCE_BUILD}/SC2.app'
    if not (source / 'SC2Data').is_dir() or not (source / '.build.info').is_file():
        raise FileNotFoundError('A complete SC2 installation with SC2Data and .build.info is required')
    if file_sha256(bundle / 'Contents/MacOS/SC2') != SOURCE_SHA256:
        raise RuntimeError('This adapter requires the verified macOS Base98310 source installation')
    manifest = _bundle_manifest()
    files = manifest['files']
    build_info = _select_build_info((source / '.build.info').read_text(encoding='utf-8'))
    # Verify source dependencies before spending time on a download or publishing
    # a bundle. Paths are pinned metadata, never archive-supplied extraction paths.
    def verify(item):
        path = bundle / item['path']
        if bundle not in path.resolve().parents or not path.is_file():
            raise ValueError(f'Missing or external bundle resource: {item["path"]}')
        if path.stat().st_size != item['source_size'] or hashlib.md5(path.read_bytes()).hexdigest() != item['source_md5']:
            raise ValueError(f'Unsupported source bundle resource: {item["path"]}')
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(verify, files))
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.mpsc2-prepare-', dir=destination.parent))
    try:
        restored = stage / 'Versions/Base96883/SC2.app'
        for item in files:
            target = restored / item['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            if 'download' in item:
                target.write_bytes(_download_file(item, cache, progress))
            else:
                shutil.copyfile(bundle / item['path'], target)
            with target.open('rb') as stream:
                magic = stream.read(4)
            executable = item['path'] == 'Contents/MacOS/SC2' or magic in (
                b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca')
            target.chmod(0o755 if executable else 0o644)
            if file_sha256(target) != item['sha256']:
                raise ValueError(f'Source resource changed during preparation: {item["path"]}')
        # Own configuration files; share the large installed content cache. Do
        # not point a configuration symlink into the retail installation.
        data = stage / 'SC2Data'
        data.mkdir()
        for original in (source / 'SC2Data').iterdir():
            if original.name == 'config':
                shutil.copytree(original, data / 'config')
            else:
                (data / original.name).symlink_to(original, target_is_directory=original.is_dir())
        config = data / 'config' / BUILD_CONFIG_KEY[:2] / BUILD_CONFIG_KEY[2:4] / BUILD_CONFIG_KEY
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(manifest['build_config']['text'], encoding='utf-8')
        linked = []
        for name in ('Maps', 'Mods', 'Campaigns', 'Support', 'Support64', 'Battle.net'):
            original = source / name
            if original.exists():
                (stage / name).symlink_to(original, target_is_directory=original.is_dir())
                linked.append(name)
        (stage / '.build.info').write_text(build_info, encoding='utf-8')
        receipt = {
            'format': 1, 'profile': MACOS_96883.id, 'engine_build': MACOS_96883.build,
            'engine_sha256': MACOS_96883.executable_sha256,
            'source_build': SOURCE_BUILD, 'source_root': str(source), 'root': str(destination),
            'source_engine_sha256': SOURCE_SHA256, 'resource_manifest_sha256': BUNDLE_MANIFEST_SHA256,
            'linked_folders': linked, 'build_info_sha256': file_sha256(stage / '.build.info'),
            'content_selection': 'pinned Base96883 build configuration with shared installed content cache',
            'data_version': DATA_VERSION, 'build_config': BUILD_CONFIG_KEY,
            'native_base98310_support': False, 'live_validation': 'not run by this command',
            'select_with': {'SC2PATH': str(destination)},
        }
        (stage / RECEIPT_NAME).write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f'Destination appeared during preparation: {destination}')
        stage.rename(destination)
        if progress:
            progress('Prepared Base96883 compatibility engine; set SC2PATH to the returned root')
        return receipt
    finally:
        if stage.exists():
            shutil.rmtree(stage)


__all__ = ['prepare_macos_compat']
