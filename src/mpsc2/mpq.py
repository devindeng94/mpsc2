"""Minimal deterministic MPQ writer shared by the map builders."""
from pathlib import Path
import struct

import mpyq


def encrypt_table(data: bytes, key: int, archive: mpyq.MPQArchive) -> bytes:
    seed = 0xEEEEEEEE
    output = bytearray()
    for (value,) in struct.iter_unpack("<I", data):
        seed = (seed + archive.encryption_table[0x400 + (key & 0xFF)]) & 0xFFFFFFFF
        output += struct.pack("<I", (value ^ (key + seed)) & 0xFFFFFFFF)
        key = (((~key << 21) + 0x11111111) | (key >> 11)) & 0xFFFFFFFF
        seed = (value + seed + (seed << 5) + 3) & 0xFFFFFFFF
    return bytes(output)


def write_mpq(path: Path, files: dict[bytes, bytes], template: mpyq.MPQArchive) -> None:
    files = dict(files)
    files[b"(listfile)"] = b"\r\n".join(sorted(files)) + b"\r\n"
    table_size = 1 << (len(files) * 2 - 1).bit_length()
    hashes = [b"\xff" * 16 for _ in range(table_size)]
    blocks = bytearray()
    payload = bytearray()
    for i, (name, data) in enumerate(sorted(files.items())):
        slot = template._hash(name, "TABLE_OFFSET") % table_size
        while hashes[slot] != b"\xff" * 16:
            slot = (slot + 1) % table_size
        hashes[slot] = struct.pack("<IIHHI", template._hash(name, "HASH_A"),
                                   template._hash(name, "HASH_B"), 0, 0, i)
        blocks += struct.pack("<4I", 32 + len(payload), len(data), len(data), 0x81000000)
        payload += data
    hash_offset = 32 + len(payload)
    block_offset = hash_offset + table_size * 16
    header = struct.pack("<4sIIHHIIII", b"MPQ\x1a", 32, block_offset + len(blocks),
                         0, 3, hash_offset, block_offset, table_size, len(files))
    path.write_bytes(header + payload
                     + encrypt_table(b"".join(hashes), template._hash(b"(hash table)", "TABLE"), template)
                     + encrypt_table(bytes(blocks), template._hash(b"(block table)", "TABLE"), template))
    check = mpyq.MPQArchive(str(path))
    try:
        for name, data in files.items():
            if check.read_file(name) != data:
                raise ValueError(f"Archive round-trip failed: {name!r}")
    finally:
        check.file.close()
