import asyncio
from pathlib import Path
import struct
from unittest.mock import AsyncMock, patch

import mpyq
import pytest
from sc2.bot_ai import BotAI
from sc2.data import Race, Result
from sc2.player import Bot

from mpsc2 import maps, run_game, GameMatch, run_multiple_games
from mpsc2.arena import prepare_map, melee_layout, melee_positions, normalize_teams, PLAYABLE_BOUNDS
from mpsc2.native_session import NativeMultiplayerSession, NativeFourSession


@pytest.mark.parametrize('count', range(2, 9))
@pytest.mark.parametrize('scenario', ['MPSC2TeamArena', 'MPSC2Melee'])
def test_runtime_map_matches_requested_player_count(tmp_path, count, scenario):
    teams = [i % 2 for i in range(count)]
    path = prepare_map(maps.get(scenario).path, tmp_path/'map.SC2Map', teams, 5)
    archive = mpyq.MPQArchive(str(path))
    try:
        info = archive.read_file('MapInfo')
        assert struct.unpack_from('<I', info, 138)[0] == count + 2
        records = [info[142+23*i:142+23*(i+1)] for i in range(count+2)]
        assert [r[0] for r in records] == [0, *range(1, count+1), 15]
        assert [struct.unpack_from('<I', r, 1)[0] for r in records] == [3, *([1]*count), 4]
        script = archive.read_file('MapScript.galaxy').decode()
        assert f'int[{count+1}] groups;' in script
        assert f'for (p = 1; p <= {count}; p += 1)' in script
        assert f'MPSC2-SLOT-{count}"' in script
        assert f'MPSC2-SLOT-{count+1}"' not in script
        for token in ['PLAYER_COUNT', 'SLOT_ARRAY_SIZE', '// SLOT_MESSAGES', 'TIME_LIMIT', 'REALTIME_MODE']:
            assert token not in script
        if scenario == 'MPSC2Melee':
            assert script.count('ResourceBase(') == 2*count+1
            assert script.count('StartBase(p,') == count
        else:
            assert script.count('UnitCreate(6, "Marine"') == count
    finally:
        archive.file.close()


@pytest.mark.parametrize('count', range(2, 9))
def test_all_counts_reach_runner_and_default_to_ffa(count):
    players = [Bot(Race.Terran, BotAI()) for _ in range(count)]
    with patch('mpsc2.main._run_multiplayer_game_async', new_callable=AsyncMock, return_value=[Result.Tie]*count) as run:
        assert run_game('MPSC2TeamArena', players) == [Result.Tie]*count
    assert run.call_args.kwargs['team_ids'] == tuple(range(count))


@pytest.mark.parametrize('count', range(2, 9))
def test_melee_sites_are_distinct_and_on_terrain(count):
    bases, expansions = melee_layout(count)
    assert len(bases) == len(expansions) == count
    assert len(set(bases+expansions)) == count*2
    left, bottom, right, top = PLAYABLE_BOUNDS
    for x, y in bases+expansions:
        assert left+3 <= x <= right-3 and bottom+3 <= y <= top-3
        side = -1 if x < 64 else 1
        assert left+1 <= x + side*7 <= right-1  # mineral line footprint
        assert bottom+2 <= y-10 and y+10 <= top-2  # geyser footprints
    positions = melee_positions([i % 2 for i in range(count)])
    assert set(positions) == set(range(1,count+1))


@pytest.mark.parametrize('count', [0, 1, 9, 16])
def test_invalid_counts_rejected_before_launch(count):
    with pytest.raises(ValueError):
        normalize_teams(list(range(count)))
    with pytest.raises(ValueError):
        NativeMultiplayerSession(Path('does-not-exist.SC2Map'), output=Path('unused'), players=count)


def test_team_count_must_match_players():
    with pytest.raises(ValueError, match='one integer ID per player'):
        run_game('MPSC2TeamArena', [Bot(Race.Terran, BotAI()) for _ in range(5)], team_ids=[0,1,0,1])


def test_two_player_batch_uses_multiplayer_fixture_without_bridge():
    players = [Bot(Race.Terran, BotAI()) for _ in range(2)]
    with patch('mpsc2.main.run_game_async', new_callable=AsyncMock, return_value=[Result.Tie]*2) as run:
        result = run_multiple_games([GameMatch('MPSC2TeamArena', players)])
    assert list(result[0]) == players
    run.assert_awaited_once()


def test_legacy_four_player_session_preserved(tmp_path):
    p = tmp_path/'map.SC2Map'
    p.write_bytes(b'fixture')
    old = NativeFourSession(p, output=tmp_path/'out')
    assert old.players == 4 and len(old.races) == 4
    eight = NativeMultiplayerSession(p, output=tmp_path/'eight', players=8)
    assert eight.players == 8 and len(eight.names) == 8
