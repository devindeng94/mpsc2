"""Build the pinned scenarios with a client-to-player setup handshake."""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct

import mpyq

from .mpq import write_mpq

ARENA_SHA256 = "5067d76a0ba49bf93ab8aca43011d79955da65d0bbfcc2c32ef08088fdf02af8"
MELEE_SHA256 = "8ff5697a9363ee6995381cdf5ff9a145c6aa4d9f435a5a39c6ce77e2993d2e00"
MELEE_BASES = ((30.5, 30.5), (30.5, 85.5), (97.5, 30.5), (97.5, 85.5))
MELEE_EXPANSIONS = ((53.5, 30.5), (53.5, 85.5), (74.5, 30.5), (74.5, 85.5))
MIN_PLAYERS = 2
MAX_PLAYERS = 8
# Engine-reported playable rectangle for the pinned terrain (not its 128x128 canvas).
PLAYABLE_BOUNDS = (10, 8, 118, 108)


def normalize_teams(team_ids) -> tuple[int, ...]:
    """Accept arbitrary integer labels, preserving equality and first-seen order."""
    team_ids = tuple(team_ids)
    if not MIN_PLAYERS <= len(team_ids) <= MAX_PLAYERS or any(type(t) is not int for t in team_ids):
        raise ValueError("team_ids must contain 2..8 integer IDs, one per player")
    unique = tuple(dict.fromkeys(team_ids))
    if len(unique) < 2:
        raise ValueError("At least two opposing teams are required")
    return tuple(unique.index(t) + 1 for t in team_ids)


def validate_map(source: Path) -> str:
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest == ARENA_SHA256:
        return "arena"
    if digest == MELEE_SHA256:
        return "melee"
    raise ValueError("This runner supports maps/MPSC2TeamArena.SC2Map and maps/MPSC2Melee.SC2Map only; "
                     "other maps need their own team setup and victory rules")


def melee_layout(player_count: int):
    """Public base/expansion sites; preserve the original four-player topology."""
    if type(player_count) is not int or not MIN_PLAYERS <= player_count <= MAX_PLAYERS:
        raise ValueError('Expected 2..8 players')
    if player_count <= 4:
        indices = (0, 2) if player_count == 2 else tuple(range(player_count))
        return tuple(MELEE_BASES[i] for i in indices), tuple(MELEE_EXPANSIONS[i] for i in indices)
    left = (player_count + 1) // 2
    right = player_count - left
    # Leave room for the full resource line and geyser footprints at the edges.
    # A y=108.5 fourth row is outside this terrain's playable rectangle: the
    # engine relocates bases and leaves some workers unable to reach resources.
    bases = tuple((24.5, 20.5 + 25*i) for i in range(left)) + tuple((103.5, 20.5 + 25*i) for i in range(right))
    expansions = tuple((50.5 if x < 64 else 77.5, y) for x, y in bases)
    return bases, expansions


def melee_positions(team_ids) -> dict[int, tuple[float, float]]:
    """Input slot (one-based) to base; adjacent slots are assigned to teammates."""
    groups = normalize_teams(team_ids)
    order = sorted(range(len(groups)), key=lambda i: (groups[i], i))
    return {index + 1: pos for index, pos in zip(order, melee_layout(len(groups))[0])}


def runtime_script(team_ids, game_time_limit: float, *, realtime=False, scenario="arena") -> str:
    groups = normalize_teams(team_ids)
    count = len(groups)
    script = Path(__file__).with_name("RuntimeArena.galaxy").read_text()
    script = script.replace('PLAYER_COUNT', str(count)).replace('SLOT_ARRAY_SIZE', str(count + 1))
    script = script.replace('// SLOT_MESSAGES', '\n    '.join(
        f'if (EventChatMessage(false) == "MPSC2-SLOT-{i}") {{ slot = {i}; }}' for i in range(1, count + 1)))
    script = script.replace("// GROUP_ASSIGNMENTS", "\n    ".join(
        f"if (slot == {slot}) {{ return {group}; }}" for slot, group in enumerate(groups, 1)))
    # Keep teammates together, including non-contiguous input like [7, 9, 7, 9].
    order = sorted(range(count), key=lambda i: (groups[i], i))
    positions = [(48, 48), (48, 66), (80, 48), (80, 66)]
    if count != 4:
        left = (count + 1) // 2
        positions = [(44, 34 + 16*i) for i in range(left)] + [(84, 34 + 16*i) for i in range(count-left)]
    if sorted(groups.count(g) for g in set(groups)) == [1, 3]:
        majority = next(g for g in groups if groups.count(g) == 3)
        order = [i for i, g in enumerate(groups) if g == majority] + [groups.index(next(g for g in groups if g != majority))]
        positions = [(48, 45), (46, 57), (48, 69), (82, 57)]
    if scenario == "melee":
        helpers = Path(__file__).with_name("Melee.galaxy").read_text()
        world = "\n    ".join(
            f"ResourceBase({x}, {y}, {'-1.0' if x < 64 else '1.0'});"
            for x, y in sum(melee_layout(count), ()))
        spawns = "\n        ".join(
            f"if (slots[p] == {slot}) {{ StartBase(p, {x}, {y}); }}"
            for slot, (x, y) in melee_positions(team_ids).items())
    elif scenario == "arena":
        helpers = "bool HasSurvivors(int p) { return UnitGroupCount(armies[p], c_unitCountAlive) > 0; }"
        world = ""
        spawns = "\n        ".join(
            f'if (slots[p] == {index+1}) {{ armies[p] = UnitCreate(6, "Marine", 0, p, Point({x}.0, {y}.0), 0.0); }}'
            for index, (x, y) in zip(order, positions))
    else:
        raise ValueError(f"Unknown scenario: {scenario}")
    script = script.replace("// SCENARIO_HELPERS", helpers)
    script = script.replace("// SETUP_WORLD", world)
    script = script.replace("// ARMY_SPAWNS", spawns)
    script = script.replace("TIME_LIMIT", f"{game_time_limit:.4f}")
    script = script.replace("REALTIME_MODE", "true" if realtime else "false")
    return script


def prepare_map(source: Path, destination: Path, team_ids, game_time_limit: float, *, realtime=False) -> Path:
    """Copy a pinned scenario, replacing only metadata and its trigger script."""
    scenario = validate_map(source)
    if destination.exists():
        raise FileExistsError(destination)
    team_ids = tuple(team_ids)
    script = runtime_script(team_ids, game_time_limit, realtime=realtime, scenario=scenario)
    archive = mpyq.MPQArchive(str(source))
    try:
        files = {name: archive.read_file(name) for name in archive.files}
        files[b"MapScript.galaxy"] = script.encode()
        files[b"MapInfo"] = resize_map_info(files[b"MapInfo"], len(team_ids))
        files[b"enUS.SC2Data\\LocalizedData\\GameStrings.txt"] = (
            "DocInfo/Name=MPSC2 Runtime Teams\n"
            f"DocInfo/DescLong={len(team_ids)} independent clients; teams configured before combat.\n"
        ).encode()
        destination.parent.mkdir(parents=True, exist_ok=True)
        write_mpq(destination, files, archive)
    finally:
        archive.file.close()
    return destination


def resize_map_info(info: bytes, player_count: int) -> bytes:
    """Resize only the known, checksum-guarded fixture's 23-byte slot records."""
    if type(player_count) is not int or not MIN_PLAYERS <= player_count <= MAX_PLAYERS:
        raise ValueError('Expected 2..8 players')
    if info[:8] != b'IpaM\x26\x00\x00\x00' or len(info) < 142:
        raise ValueError('Unexpected MapInfo layout')
    old_count = struct.unpack_from('<I', info, 138)[0]
    end = 142 + 23 * old_count
    if old_count != 6 or len(info) != 332 or info[142] != 0 or info[165] != 1 or info[end-23] != 15:
        raise ValueError('Unexpected pinned MapInfo player records')
    players = []
    for pid in range(1, player_count + 1):
        record = bytearray(info[165:188])
        record[0] = pid
        struct.pack_into('<i', record, 5, pid - 1)
        players.append(bytes(record))
    return info[:138] + struct.pack('<I', player_count + 2) + info[142:165] + b''.join(players) + info[end-23:]
