"""Build the four-slot map reproducibly from a checksum-pinned Blizzard fixture.

The MPQ writer intentionally supports only uncompressed single-unit files, which
is enough for this small map. mpyq independently reads every entry after writing.
MapInfo offsets are specific to the pinned Empty.SC2Map, never arbitrary maps.
"""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import mpyq

from mpsc2.mpq import write_mpq

ROOT = Path(__file__).resolve().parents[1]
BASE_SHA256 = "a69d524e36b4f348ab310dab8d6dae16ba1fd8858f1073f07db9733773c08a46"


def four_player_info(info: bytes, groups=(0, 0, 1, 1)) -> bytes:
    if len(groups) != 4 or any(type(g) is not int or not 0 <= g <= 3 for g in groups):
        raise ValueError("Expected four group IDs in 0..3")
    if info[:8] != b"IpaM\x26\x00\x00\x00" or len(info) != 263:
        raise ValueError("Unexpected MapInfo layout")
    if struct.unpack_from("<I", info, 138)[0] != 3:
        raise ValueError("Unexpected base player count")
    neutral, player, hostile = info[142:165], info[165:188], info[188:211]
    if (neutral[0], player[0], hostile[0]) != (0, 1, 15):
        raise ValueError("Unexpected base player slots")
    players = []
    for pid in range(1, 5):
        entry = bytearray(player)
        entry[0] = pid
        struct.pack_into("<i", entry, 5, groups[pid - 1])  # editor team
        players.append(bytes(entry))
    return info[:138] + struct.pack("<I", 6) + neutral + b"".join(players) + hostile + info[211:]


def build(output: Path | None = None, *, groups=(0, 0, 1, 1), script: bytes | None = None,
          title="MPSC2 Team Arena") -> Path:
    if tuple(groups) != (0, 0, 1, 1) and script is None:
        raise ValueError("Non-default groups require a matching Galaxy alliance script")
    base = ROOT / "maps/vendor/Empty.SC2Map"
    if hashlib.sha256(base.read_bytes()).hexdigest() != BASE_SHA256:
        raise ValueError("Base map checksum mismatch; refusing to patch unknown binary")
    archive = mpyq.MPQArchive(str(base))
    try:
        files = {name: archive.read_file(name) for name in archive.files}
        files[b"MapInfo"] = four_player_info(files[b"MapInfo"], groups)
        files[b"MapScript.galaxy"] = script if script is not None else (ROOT / "maps/source/MapScript.galaxy").read_bytes()
        files[b"enUS.SC2Data\\LocalizedData\\GameStrings.txt"] = (
            "DocInfo/Name=MPSC2 Team Arena\n"
            "DocInfo/DescLong=Four independent players: 1+2 versus 3+4. Six marines each.\n"
            "DocInfo/DescShort=2v2 research launch fixture\n"
            "MapInfo/Player00/Name=Neutral\n"
            "MapInfo/Player01/Name=Team A - 1\n"
            "MapInfo/Player02/Name=Team A - 2\n"
            "MapInfo/Player03/Name=Team B - 1\n"
            "MapInfo/Player04/Name=Team B - 2\n"
            "MapInfo/Player05/Name=Hostile\n"
        ).encode()
        if script is not None:
            files[b"enUS.SC2Data\\LocalizedData\\GameStrings.txt"] = (
                f"DocInfo/Name={title}\n"
                "DocInfo/DescLong=Four independent API players. Native map alliances.\n"
                "DocInfo/DescShort=Multiplayer combat demonstration\n"
                "MapInfo/Player00/Name=Neutral\n"
                + "".join(f"MapInfo/Player{p:02}/Name=Player {p} - Group {groups[p-1]+1}\n" for p in range(1, 5))
                + "MapInfo/Player05/Name=Hostile\n"
            ).encode()
        output = output or ROOT / "maps/MPSC2TeamArena.SC2Map"
        output.parent.mkdir(parents=True, exist_ok=True)
        write_mpq(output, files, archive)
        return output
    finally:
        archive.file.close()


if __name__ == "__main__":
    result = build()
    print(f"Built {result} ({result.stat().st_size} bytes)")
    print(f"SHA256: {hashlib.sha256(result.read_bytes()).hexdigest()}")
