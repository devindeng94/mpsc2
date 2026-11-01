import asyncio
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import mpsc2
from mpsc2.versions import (GAME_VERSIONS, NATIVE_PROFILES, WINDOWS_93333, WINDOWS_98370, MACOS_96883,
    UnsupportedNativeProfile, get_game_version, get_native_profile, compatibility_catalog, write_windows_header)


def test_original_upstream_versions_export_is_preserved():
    from sc2.versions import VERSIONS as upstream
    from mpsc2.versions import VERSIONS
    assert VERSIONS is upstream


def test_native_loader_refuses_a_different_python_architecture(tmp_path):
    from mpsc2.windows_session import validate_executable
    executable = tmp_path/'SC2_x64.exe'
    executable.touch()
    with patch('mpsc2.windows_session.file_sha256', return_value=WINDOWS_93333.executable_sha256), \
         patch('mpsc2.windows_session.c.sizeof', return_value=8), \
         patch('mpsc2.windows_session.sysconfig.get_platform', return_value='win-arm64'):
        with pytest.raises(RuntimeError, match='x86_64 Windows Python'):
            validate_executable(executable)


@pytest.mark.parametrize('value', ['4.10', '4.10.0', 'Base75689', '75689', 75689])
def test_legacy_game_aliases_resolve_only_for_registered_platforms(value):
    game = get_game_version(value)
    assert game.build == 75689 and game.data_version == 'B89B5D6FA7CBF6452E721311BFBC6CB2'
    with pytest.raises(UnsupportedNativeProfile, match='No verified native'):
        get_native_profile('Darwin', value)
    assert get_native_profile('Windows', value).build == 75689
    assert get_native_profile('Linux', value).build == 75689


@pytest.mark.parametrize('system,version', [('Windows', 'Base92440'), ('Windows', '5.0.15.96883'),
    ('Darwin', '5.0.14'), ('Linux', '5.0.14'), ('Windows', 'latest'), ('Windows', '../Base93333')])
def test_no_fallback_for_unknown_or_foreign_profiles(system, version):
    with pytest.raises(UnsupportedNativeProfile):
        get_native_profile(system, version)


def test_defaults_and_binary_architecture_are_explicit():
    assert get_native_profile('Windows') is WINDOWS_93333
    assert get_native_profile('Darwin') is MACOS_96883
    assert get_native_profile('Windows', '5.0.14.93333') is WINDOWS_93333
    with pytest.raises(UnsupportedNativeProfile):
        get_native_profile('Windows', architecture='arm64')
    assert len(get_game_version('5.0.14').data_version) == 32
    assert len(WINDOWS_93333.executable_sha256) == 64
    assert get_game_version('5.0.15', system='Darwin').data_version is None  # do not invent an unrecorded value


def test_registries_and_profile_settings_cannot_be_mutated():
    with pytest.raises(TypeError):
        GAME_VERSIONS['new'] = get_game_version('4.10')
    with pytest.raises(TypeError):
        NATIVE_PROFILES[('Windows', 'x86_64', 75689)] = WINDOWS_93333
    with pytest.raises(FrozenInstanceError):
        WINDOWS_93333.windows_layout.lobby_state = 1


def test_modified_profile_cannot_authorize_compilation(tmp_path):
    from mpsc2.windows_session import build_bridge
    forged = replace(WINDOWS_93333, windows_layout=replace(WINDOWS_93333.windows_layout, upgrade_fault=1))
    with patch('mpsc2.windows_session.subprocess.run') as compile_helper:
        with pytest.raises(UnsupportedNativeProfile):
            build_bridge(tmp_path, forged)
    compile_helper.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_macos_profile_binds_the_unchanged_helpers():
    from mpsc2.native_session import _macos_helper_source
    for i, name in enumerate(MACOS_96883.helper_sources):
        path = _macos_helper_source(MACOS_96883, i)
        assert path == Path(mpsc2.__file__).parent / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == MACOS_96883.helper_source_sha256[i]


def test_macos_changed_helper_refused_before_compilation(tmp_path):
    from mpsc2.native_session import build_bridge
    with patch('mpsc2.native_session.hashlib.sha256') as digest, \
         patch('mpsc2.native_session.subprocess.run') as compile_helper:
        digest.return_value.hexdigest.return_value = '0'*64
        with pytest.raises(RuntimeError, match='helper source differs'):
            build_bridge(tmp_path)
    compile_helper.assert_not_called()


def test_public_native_version_selection_reaches_session(tmp_path):
    from mpsc2.player import Bot
    from mpsc2.data import Race
    from mpsc2.bot_ai import BotAI
    players = [Bot(Race.Terran, BotAI()) for _ in range(4)]
    with patch('platform.system', return_value='Windows'), \
         patch('mpsc2.main.NativeMultiplayerSession', side_effect=RuntimeError('launch boundary')) as session:
        with pytest.raises(RuntimeError, match='launch boundary'):
            mpsc2.run_game('MPSC2TeamArena', players, sc2_version='5.0.14', output_dir=tmp_path/'run')
    assert session.call_args.kwargs['sc2_version'] == '5.0.14'


def test_unsupported_public_selection_refuses_before_map_or_output(tmp_path):
    from mpsc2.player import Bot
    from mpsc2.data import Race
    from mpsc2.bot_ai import BotAI
    players = [Bot(Race.Terran, BotAI()) for _ in range(4)]
    with patch('platform.system', return_value='Windows'), patch('mpsc2.main.NativeMultiplayerSession') as session:
        with pytest.raises(UnsupportedNativeProfile, match='Base96883'):
            mpsc2.run_game('MPSC2TeamArena', players, sc2_version='Base96883', output_dir=tmp_path/'run')
    session.assert_not_called()
    assert not (tmp_path/'run').exists()


def test_helper_report_with_wrong_profile_is_refused(tmp_path):
    from mpsc2.windows_session import WindowsProcess
    process = WindowsProcess.__new__(WindowsProcess)
    process.profile = WINDOWS_93333
    process.helper = tmp_path/'helper.dll'
    process.output = tmp_path
    process._process = SimpleNamespace(pid=17)
    process.env = {'MPSC2_WINDOWS_GUARD_LOG': str(tmp_path/'observation-guard.json')}
    with patch('mpsc2.native_session.NativeProcess._connect', new_callable=AsyncMock, return_value=object()), \
         patch('mpsc2.windows_session.load_bridge'), \
         patch('mpsc2.windows_session.wait_record', new_callable=AsyncMock,
               return_value={'applied': True, 'pid': 17, 'profile_id': 'another-profile'}):
        with pytest.raises(RuntimeError, match='guard refused'):
            asyncio.run(process._connect())


def test_catalog_is_available_without_installation_or_compiler(capsys):
    from mpsc2.cli import main
    with patch('mpsc2.installation.detect_installation', side_effect=AssertionError('not required')), \
         patch('subprocess.Popen', side_effect=AssertionError('must not launch')):
        assert main(['versions']) == 0
    catalog = json.loads(capsys.readouterr().out)
    assert {p['build'] for p in catalog['native_profiles']} == {75689, 93333, 96883, 98370}
    assert any(o['build'] == 92440 and o['standard_api'] == 'unverified' for o in catalog['observations'])


def test_doctor_explicit_unsupported_build_reports_failure(tmp_path, monkeypatch):
    from mpsc2.capabilities import get_capabilities
    from mpsc2.installation import upstream
    monkeypatch.setenv('SC2PATH', str(tmp_path))
    with patch('platform.system', return_value='Windows'), patch.object(upstream, 'platform_detect', return_value='Windows'):
        native = get_capabilities('Base96883')['multiplayer']
    assert not native['ready'] and not native['supported'] and native['profile'] is None
    assert 'Base96883' in native['errors'][0]


def test_native_batch_forwards_version_selection():
    from mpsc2.player import Bot
    from mpsc2.data import Race, Result
    from mpsc2.bot_ai import BotAI
    match = mpsc2.GameMatch('MPSC2TeamArena', [Bot(Race.Terran, BotAI()) for _ in range(4)], sc2_version='5.0.14')
    with patch('mpsc2.main.run_game_async', new_callable=AsyncMock, return_value=[Result.Tie]*4) as run:
        mpsc2.run_multiple_games([match])
    assert run.call_args.kwargs['sc2_version'] == '5.0.14'


def test_generated_profile_matches_all_original_windows_addresses(tmp_path):
    # Regression fixture independent of the registry: moving a constant would
    # otherwise pass a test that generated both its actual and expected values.
    header = write_windows_header(tmp_path).read_text(encoding='utf-8')
    for macro, address in {'LOBBY_STATE': '40381dc', 'HOST_FLAG': '43a7d90', 'API_COUNT': '43a7d94',
        'COMPUTER_COUNT': '43a7d98', 'ROSTER_POINTER': '43a84e8', 'ROSTER_COUNT': '43a84f0',
        'READINESS_POINTER': '4038270', 'LOBBY_CHECK': 'd297f7', 'READINESS_CHECK': 'f48b1f',
        'OPPONENT_UPGRADE': 'b3dbe4', 'OWN_UPGRADE': 'b3db99', 'UPGRADE_CLEANUP': 'b3dc2c',
        'UPGRADE_FAULT': 'b3dbef'}.items():
        assert f'#define MPSC2_{macro}_RVA 0x{address}ULL' in header


@pytest.mark.parametrize('count', [2, 4, 8])
def test_macos_profile_preserves_session_handshake_and_environment(tmp_path, monkeypatch, count):
    from s2clientprotocol import sc2api_pb2 as api
    from mpsc2.native_session import NativeMultiplayerSession
    source = tmp_path/'fixture.SC2Map'
    source.touch()
    helper, guard = tmp_path/'bridge.dylib', tmp_path/'guard.dylib'
    helper.write_bytes(b'bridge fixture')
    guard.write_bytes(b'guard fixture')
    monkeypatch.setenv('SC2PATH', str(tmp_path))
    session = NativeMultiplayerSession(source, output=tmp_path/'run', players=count, sc2_version='5.0.15')
    processes, clients, environments = [], [], []
    response = api.Response(create_game=api.ResponseCreateGame())
    if count > 2:
        response.create_game.error = api.ResponseCreateGame.InvalidPlayerSetup
        response.create_game.error_details = 'Only 1v1 is supported when using multiple agents'
    def make_process(executable, root, output, env, index, **kwargs):
        assert executable == MACOS_96883.executable(tmp_path)
        output.mkdir()
        process = AsyncMock()
        process._process = SimpleNamespace(pid=100+index)
        process._port = 5000+index
        process.observation_guard = {'applied': True} if count > 2 else None
        process.__aenter__.return_value._execute.return_value = response
        processes.append(process)
        environments.append(env)
        return process
    def make_client(*args, **kwargs):
        client = AsyncMock()
        client.join_game.return_value = len(clients)+1
        client.ping.return_value = api.Response(status=api.init_game)
        clients.append(client)
        return client
    async def run():
        async with session:
            assert session.player_ids == list(range(1, count+1))
    with patch('platform.system', return_value='Darwin'), \
         patch('mpsc2.native_session.validate_executable') as validate, \
         patch('mpsc2.native_session.build_bridge', return_value=helper) as bridge, \
         patch('mpsc2.native_session.build_observation_guard', return_value=guard) as observation, \
         patch('mpsc2.native_session.NativeProcess', side_effect=make_process), \
         patch('mpsc2.native_session.RecordedClient', side_effect=make_client), \
         patch('mpsc2.native_session.wait_record', new_callable=AsyncMock,
               return_value={'promoted': True, 'held': True, 'native_ready_players': count}):
        asyncio.run(run())
    validate.assert_called_once_with(MACOS_96883.executable(tmp_path), MACOS_96883)
    assert bridge.call_count == observation.call_count == int(count > 2)
    assert all(process.__aexit__.await_count == 1 for process in processes)
    assert session.native_metadata['profile']['id'] == MACOS_96883.id
    for index, env in enumerate(environments):
        if count == 2:
            assert 'DYLD_INSERT_LIBRARIES' not in env
        else:
            assert str(guard) in env['DYLD_INSERT_LIBRARIES']
            assert (str(helper) in env['DYLD_INSERT_LIBRARIES']) == (index == 0)
            assert ('MPSC2_BRIDGE_DIR' in env) == (index == 0)
            assert env['MPSC2_OBSERVATION_GUARD_LOG'].endswith('observation-guard.json')
        assert 'MPSC2_WINDOWS_GUARD_LOG' not in env


def test_same_patch_label_selects_the_platform_specific_build():
    assert get_native_profile('Windows', '5.0.15') is WINDOWS_98370
    assert get_native_profile('Darwin', '5.0.15') is MACOS_96883
    assert get_game_version('5.0.15', system='Windows').data_version == '84197ED58A0329FA79CC9426E07E5FB3'
    with pytest.raises(ValueError, match='Ambiguous'):
        get_game_version('5.0.15')
    with pytest.raises(UnsupportedNativeProfile):
        get_native_profile('Darwin', 'Base98370')
    assert get_native_profile('Windows', 98370) is WINDOWS_98370
