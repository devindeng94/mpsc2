import hashlib
import importlib.util
from pathlib import Path
import struct

import mpyq
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_map", ROOT / "scripts/build_map.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_map_archive_and_four_playable_slots(tmp_path):
    path = builder.build(tmp_path / "arena.SC2Map")
    archive = mpyq.MPQArchive(str(path))
    try:
        info = archive.read_file("MapInfo")
        assert struct.unpack_from("<I", info, 138)[0] == 6
        entries = [info[142 + 23 * i:142 + 23 * (i + 1)] for i in range(6)]
        assert [entry[0] for entry in entries] == [0, 1, 2, 3, 4, 15]
        assert [struct.unpack_from("<I", entry, 1)[0] for entry in entries] == [3, 1, 1, 1, 1, 4]
        assert [struct.unpack_from("<i", entry, 5)[0] for entry in entries[1:5]] == [0, 0, 1, 1]
        assert archive.read_file("MapScript.galaxy") == (ROOT / "maps/source/MapScript.galaxy").read_bytes()
    finally:
        archive.file.close()
    assert hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(builder.build(tmp_path / "again.SC2Map").read_bytes()).digest()


def test_reject_unrecognized_mapinfo():
    with pytest.raises(ValueError, match="layout"):
        builder.four_player_info(b"not a map")


@pytest.mark.parametrize('groups', [(0,1,2,3),(0,0,0,1)])
def test_alternative_native_team_layouts(tmp_path, groups):
    # Read the actual MPQ layout, independently of the builder's inputs.
    path = builder.build(tmp_path / 'variant.SC2Map', groups=groups,
                         script=b'// test script\n', title='Variant')
    archive = mpyq.MPQArchive(str(path))
    try:
        info = archive.read_file('MapInfo')
        entries = [info[142+23*i:142+23*(i+1)] for i in range(1,5)]
        assert [struct.unpack_from('<i', entry, 5)[0] for entry in entries] == list(groups)
        assert archive.read_file('MapScript.galaxy') == b'// test script\n'
    finally:
        archive.file.close()
