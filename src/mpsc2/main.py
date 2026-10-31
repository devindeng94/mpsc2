"""python-sc2-style BotAI lifecycle for 2..8 independent SC2 clients."""
from __future__ import annotations

import asyncio
from collections import Counter
import json
import math
from pathlib import Path
from secrets import randbits
import time
from typing import Sequence
from uuid import uuid4

from sc2.bot_ai import BotAI
from sc2.constants import mineral_ids, geyser_ids
from sc2.data import Race, Result, Status
from sc2.game_state import GameState
from sc2.maps import Map
from sc2.player import Bot
from sc2.position import Point2
from sc2.ids.unit_typeid import UnitTypeId
from sc2.protocol import ProtocolError
from s2clientprotocol import raw_pb2 as raw, sc2api_pb2 as api

from .arena import normalize_teams, prepare_map, validate_map, melee_positions
from .native_session import NativeMultiplayerSession
from .session import barrier


def _sync(coroutine, async_name):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    coroutine.close()
    raise RuntimeError(f"Use await {async_name}(...) inside an existing event loop")


def _is_multiplayer_map(map_settings):
    try:
        validate_map(Path(_map(map_settings).path))
        return True
    except ValueError:
        return False


def _standard_options(players, team_ids, output_dir, step_size, timeout, graphics_api, window_size, map_settings):
    if not 1 <= len(players) <= 8:
        raise ValueError("Expected one/two standard players or 2..8 multiplayer Bot players")
    if len(players) > 2:
        return False
    if team_ids is not None:
        if len(players) == 2:
            return False
        raise ValueError("team_ids requires 2..8 players; omit it for standard python-sc2 games")
    if len(players) == 2 and all(isinstance(p, Bot) for p in players) and _is_multiplayer_map(map_settings):
        return False
    if output_dir is not None or step_size != 8 or timeout != 90 or graphics_api is not None or window_size is not None:
        raise NotImplementedError("output_dir, step_size, timeout, graphics_api and window_size overrides apply to multiplayer scenarios only")
    return True


def _map(map_settings):
    from . import maps
    return map_settings if isinstance(map_settings, Map) else maps.get(map_settings)


def _standard_map(map_settings):
    game_map = _map(map_settings)
    try:
        validate_map(Path(game_map.path))
    except ValueError:
        return game_map
    raise ValueError("MPSC2 multiplayer scenarios require 2..8 Bot players; use a standard map for built-in Computer/Human opponents")


def run_game(
    map_settings, players, realtime=False, portconfig=None, save_replay_as=None,
    game_time_limit=None, rgb_render_config=None, random_seed=None,
    sc2_version=None, disable_fog=False, *, team_ids=None, output_dir=None,
    step_size=8, timeout=90, graphics_api=None, window_size=None,
):
    """python-sc2-compatible launcher, extended with 2..8-player ``team_ids``.

    Standard one/two-player calls delegate to burnysc2 unchanged. Multiplayer BotAI
    players use the native multiplayer backend; omitted teams mean free-for-all.
    A missing time limit selects 120 Galaxy seconds for the arena, 900 for melee.
    Unsupported multiplayer options raise before launching processes.
    """
    players = tuple(players)
    if _standard_options(players, team_ids, output_dir, step_size, timeout, graphics_api, window_size, map_settings):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("Use await run_game_async(...) inside an existing event loop")
        from sc2.main import run_game as upstream
        return upstream(_standard_map(map_settings), list(players), realtime, portconfig,
                        str(save_replay_as) if save_replay_as is not None else None,
                        game_time_limit, rgb_render_config, random_seed, sc2_version, disable_fog)
    return _sync(run_game_async(
        map_settings, players, realtime, portconfig, save_replay_as, game_time_limit,
        rgb_render_config, random_seed, sc2_version, disable_fog, team_ids=team_ids,
        output_dir=output_dir, step_size=step_size, timeout=timeout,
        graphics_api=graphics_api, window_size=window_size,
    ), "run_game_async")


async def run_game_async(
    map_settings, players, realtime=False, portconfig=None, save_replay_as=None,
    game_time_limit=None, rgb_render_config=None, random_seed=None,
    sc2_version=None, disable_fog=False, *, team_ids=None, output_dir=None,
    step_size=8, timeout=90, graphics_api=None, window_size=None,
):
    """Awaitable launcher, including standard games inside notebooks/event loops."""
    players = tuple(players)
    if _standard_options(players, team_ids, output_dir, step_size, timeout, graphics_api, window_size, map_settings):
        from .standard import run_standard_async
        return await run_standard_async(_standard_map(map_settings), players, realtime, portconfig,
                                        save_replay_as, game_time_limit, rgb_render_config,
                                        random_seed, sc2_version, disable_fog)
    if portconfig is not None or rgb_render_config is not None:
        raise NotImplementedError("Multiplayer scenarios do not support portconfig or rgb_render_config overrides")
    if sc2_version is not None:
        import platform
        from .versions import get_native_profile
        get_native_profile(platform.system(), sc2_version)  # refuse before output/map/process work
    if graphics_api is not None and (not isinstance(graphics_api, str) or not graphics_api):
        raise ValueError("graphics_api must be a nonempty string or None")
    if window_size is not None and (not isinstance(window_size, (tuple, list)) or len(window_size) != 2 or any(type(v) is not int or v <= 0 for v in window_size)):
        raise ValueError("window_size must contain two positive integers")
    team_ids = tuple(range(len(players))) if team_ids is None else tuple(team_ids)
    # Validate before map resolution, which can consult the local SC2 installation.
    _validate(players, team_ids, realtime, step_size, game_time_limit if game_time_limit is not None else 120, timeout, random_seed)
    game_map = _map(map_settings)
    scenario = validate_map(Path(game_map.path))
    if game_time_limit is None:
        game_time_limit = 900 if scenario == "melee" else 120
    return await _run_multiplayer_game_async(
        game_map, players, realtime, team_ids=team_ids, save_replay_as=save_replay_as,
        game_time_limit=game_time_limit, random_seed=random_seed, disable_fog=disable_fog,
        output_dir=output_dir, step_size=step_size, timeout=timeout,
        graphics_api=graphics_api, window_size=window_size, sc2_version=sc2_version,
    )


def _validate(players, team_ids, realtime, step_size, game_time_limit, timeout, random_seed):
    normalize_teams(team_ids)
    if not 2 <= len(players) <= 8 or any(not isinstance(p, Bot) or not isinstance(p.ai, BotAI) for p in players):
        raise ValueError("Expected 2..8 sc2.player.Bot objects with BotAI instances")
    if len(team_ids) != len(players):
        raise ValueError('team_ids must contain one integer ID per player')
    if len({id(p.ai) for p in players}) != len(players):
        raise ValueError("Each player needs a distinct BotAI instance")
    if any(p.fullscreen for p in players):
        raise ValueError("The multiplayer runner currently supports windowed players only")
    if any(p.race not in (Race.Terran, Race.Protoss, Race.Zerg, Race.Random) for p in players):
        raise ValueError("Every player must select a playable race")
    if any(getattr(p.ai, 'raw_affects_selection', None) is not None and type(p.ai.raw_affects_selection) is not bool for p in players):
        raise ValueError('BotAI.raw_affects_selection must be bool or None')
    if type(realtime) is not bool:
        raise ValueError("realtime must be a bool")
    if type(step_size) is not int or not 1 <= step_size <= 224:
        raise ValueError("step_size must be an integer in 1..224")
    for name, value in (("game_time_limit", game_time_limit), ("timeout", timeout)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be a finite positive number")
    if not 1 <= game_time_limit <= 86400:
        raise ValueError("game_time_limit must be between 1 and 86400 game seconds")
    if random_seed is not None and (type(random_seed) is not int or not 0 <= random_seed <= 0xFFFFFFFF):
        raise ValueError("random_seed must be a uint32 integer or None")


def _check_setup(observations, player_ids, team_ids, disable_fog, scenario="arena"):
    """Check native ownership and alliances, including nonsequential join IDs."""
    team_by_id = dict(zip(player_ids, team_ids))
    expected_bases = dict(zip(player_ids, (melee_positions(team_ids)[i+1] for i in range(len(player_ids))))) if scenario == 'melee' else {}
    evidence = []
    for response, pid in zip(observations, player_ids):
        obs = response.observation.observation
        if obs.player_common.player_id != pid:
            raise RuntimeError("Observation belongs to the wrong player")
        units = [u for u in obs.raw_data.units if u.owner in team_by_id]
        counts = Counter(u.owner for u in units)
        required = set(player_ids) if disable_fog else {p for p in player_ids if team_by_id[p] == team_by_id[pid]}
        if scenario == "arena":
            if any(counts[p] != 6 for p in required):
                raise RuntimeError(f"Team setup missing armies/teammate vision for player {pid}: {dict(counts)}")
        else:
            workers = {UnitTypeId.SCV.value, UnitTypeId.PROBE.value, UnitTypeId.DRONE.value}
            bases = {UnitTypeId.COMMANDCENTER.value, UnitTypeId.NEXUS.value, UnitTypeId.HATCHERY.value}
            for owner in required:
                owned = [u for u in units if u.owner == owner]
                if (sum(u.unit_type in workers for u in owned) != 12
                        or sum(u.unit_type in bases for u in owned) != 1):
                    raise RuntimeError(f"Melee setup missing starting base/workers for player {owner}")
                base = next(u for u in owned if u.unit_type in bases)
                x, y = expected_bases[owner]
                if abs(base.pos.x - x) > 0.1 or abs(base.pos.y - y) > 0.1:
                    raise RuntimeError(f'Melee base for player {owner} was displaced from its intended position {(x,y)} to {(base.pos.x,base.pos.y)}')
            if obs.player_common.minerals != 50 or obs.player_common.vespene != 0:
                raise RuntimeError(f"Melee setup has unexpected initial resources for player {pid}")
        relations = {}
        for unit in units:
            expected = raw.Self if unit.owner == pid else raw.Ally if team_by_id[unit.owner] == team_by_id[pid] else raw.Enemy
            if unit.alliance != expected:
                raise RuntimeError(f"Wrong native alliance: player {pid}, owner {unit.owner}")
            relations[unit.owner] = raw.Alliance.Name(unit.alliance)
        evidence.append({"player_id": pid, "observed_alliances": relations, "unit_counts": dict(counts)})
    return evidence


async def _configure_teams(session, team_ids, scenario="arena"):
    # Map-init must execute before sending its chat event. Armies are not yet
    # spawned, so variable guest arrival order cannot start hostile combat.
    if session.realtime:
        # Request a future observation instead of trying to advance real time.
        await session.call([c.observation(1) for c in session.clients])
    else:
        await session.step(1)
    await session.call([c.chat_send(f"MPSC2-SLOT-{i+1}", False) for i, c in enumerate(session.clients)])
    deadline = asyncio.get_running_loop().time() + session.timeout
    attempts = 0
    while asyncio.get_running_loop().time() < deadline:
        if session.realtime:
            await asyncio.sleep(0.05)
        else:
            if attempts >= 8:
                break
            await session.step(1)
        attempts += 1
        observations = await session.observe()
        if all(any(u.owner == pid for u in o.observation.observation.raw_data.units)
               for o, pid in zip(observations, session.player_ids)):
            return observations, _check_setup(observations, session.player_ids, team_ids, session.disable_fog, scenario)
    raise RuntimeError("Map did not acknowledge all player team assignments")


async def _initialize_bot(ai, client, pid, observation, player_index, team_ids, player_ids, realtime=False, scenario="arena"):
    # Mirror burnysc2 7.3.0's _play_game_ai startup, using one joined client per AI.
    ai._initialize_variables()
    game_data = await client.get_game_data()
    game_info = await client.get_game_info()
    ping = await client.ping()
    ai._prepare_start(client, pid, game_info, game_data, realtime=realtime, base_build=ping.ping.base_build)
    ai.player_index = player_index
    ai.team_id = team_ids[player_index]
    ai.team_ids = dict(zip(player_ids, team_ids))
    ai.ally_player_ids = tuple(p for p in player_ids if p != pid and ai.team_ids[p] == ai.team_id)
    ai.enemy_player_ids = tuple(p for p in player_ids if ai.team_ids[p] != ai.team_id)
    from .team import TeamInfo
    ai.team = TeamInfo(pid, player_index, ai.team_id, ai.team_ids)
    ai.enemy_races = {p: Race(game_info.player_races[p]) for p in ai.enemy_player_ids if p in game_info.player_races}
    if scenario == "melee":
        # The fixture creates bases in Galaxy after its slot handshake. Expose
        # this public map topology like static editor start-location metadata.
        positions = melee_positions(team_ids)
        ai.player_start_locations = {p: Point2(positions[i + 1]) for i, p in enumerate(player_ids)}
        game_info.start_locations = [ai.player_start_locations[p] for p in ai.enemy_player_ids]
    proto_info = await client._execute(game_info=api.RequestGameInfo())
    ai._prepare_step(_game_state(observation), proto_info)
    await ai.on_before_start()
    ai._prepare_first_step()
    await ai.on_start()


def _game_state(response):
    """Remove stale resource snapshots co-located with currently visible nodes.

    Base96883 can return both entries with different tags for Galaxy-created
    resources. Keeping both doubles resource clusters in BotAI's expansion
    finder. Preserve unseen snapshots, visible tags, and the original response.
    """
    observation = response.observation
    units = observation.observation.raw_data.units
    resource_types = mineral_ids | geyser_ids
    def key(unit):
        return unit.unit_type, unit.pos.x, unit.pos.y
    visible = {key(u) for u in units if u.alliance == raw.Neutral and u.display_type == raw.Visible
               and u.unit_type in resource_types}
    duplicates = {i for i, u in enumerate(units) if u.alliance == raw.Neutral and u.display_type == raw.Snapshot
                  and key(u) in visible}
    if duplicates:
        observation = api.ResponseObservation()
        observation.CopyFrom(response.observation)
        del observation.observation.raw_data.units[:]
        observation.observation.raw_data.units.extend(u for i, u in enumerate(units) if i not in duplicates)
    return GameState(observation)


def _terminal_results(observations, player_ids):
    tables = [{r.player_id: Result(r.result) for r in o.observation.player_result} for o in observations]
    if not any(tables):
        return None
    if any(t != tables[0] or set(t) != set(player_ids) for t in tables):
        raise RuntimeError(f"Clients disagree on terminal results: {tables}")
    return [tables[0][pid] for pid in player_ids]


async def _bot_step(player, client, observation, iteration):
    proto_info = await client._execute(game_info=api.RequestGameInfo())
    player.ai._prepare_step(_game_state(observation), proto_info)
    await player.ai.issue_events()
    await player.ai.on_step(iteration)
    await player.ai._after_step()


def _check_step_size(value):
    if type(value) is not int or not 1 <= value <= 224:
        raise ValueError("Each bot must use an integer client.game_step in 1..224")


async def _play_realtime(session, players, observations, game_time_limit, report):
    """One paced observation/callback loop per client, with no RequestStep."""
    # Armies remain paused until every on_start callback has completed. The
    # final declaration unpauses units and starts the map's relative game timer.
    before_start = await session.observe()
    start_loop = min(o.observation.observation.game_loop for o in before_start)
    report["ready_game_loop"] = start_loop
    await session.call([c.chat_send("MPSC2-READY", False) for c in session.clients])
    report["client_iterations"] = [0] * len(players)
    report["client_game_loops"] = [o.observation.observation.game_loop for o in before_start]
    started_at = time.monotonic()

    async def run_player(index, player, client):
        previous_loop = before_start[index].observation.observation.game_loop
        iteration = 0
        while True:
            _check_step_size(client.game_step)
            target_loop = previous_loop + client.game_step

            async def observe_and_act():
                observation = await client.observation(target_loop)
                if observation.observation.player_result:
                    return observation
                current_loop = observation.observation.observation.game_loop
                if current_loop <= previous_loop:
                    raise RuntimeError("Realtime observation did not advance to a newer frame")
                if (current_loop - start_loop) / 22.4 > game_time_limit + 12:
                    raise TimeoutError("Map failed to terminate at its native game-time limit")
                try:
                    await _bot_step(player, client, observation, iteration)
                except ProtocolError as exc:
                    # GameOver can race a game-info/action request. Recover only
                    # the explicit ended-game error and confirm a native result.
                    if not exc.is_game_over_error or client._status != Status.ended:
                        raise
                    terminal = await client.observation()
                    if not terminal.observation.player_result:
                        raise
                    return terminal
                if not client.in_game:
                    if client._status == Status.ended:
                        terminal = await client.observation()
                        if terminal.observation.player_result:
                            return terminal
                    raise RuntimeError("A bot left the match; independent client resignation is not supported yet")
                return observation

            # Bound each observation/callback cycle, not the whole match. A slow
            # cooperative callback does not hold up the other clients' loops.
            observation = (await barrier([observe_and_act()], session.timeout, [client]))[0]
            current_loop = observation.observation.observation.game_loop
            report["client_game_loops"][index] = current_loop
            report["game_loop"] = max(report["client_game_loops"])
            if observation.observation.player_result:
                return observation
            previous_loop = current_loop
            iteration += 1
            report["client_iterations"][index] = iteration

    try:
        terminal = await barrier(
            [run_player(i, p, c) for i, (p, c) in enumerate(zip(players, session.clients))],
            timeout=None, clients=session.clients,
        )
        return _terminal_results(terminal, session.player_ids)
    finally:
        report["play_wall_seconds"] = time.monotonic() - started_at


async def _play(session, players, observations, game_time_limit, report):
    iteration = 0
    while True:
        loops = [o.observation.observation.game_loop for o in observations]
        report["game_loop"] = max(loops)
        report["client_game_loops"] = loops
        report["iterations"] = iteration
        # Native GameOver can stop participants on adjacent frames. Only active
        # simulation must be lockstep; terminal result tables must agree in full.
        results = _terminal_results(observations, session.player_ids)
        if results is not None:
            return results
        if len(set(loops)) != 1:
            raise RuntimeError(f"Clients lost simulation synchronization: {loops}")
        if report["game_loop"] / 22.4 > game_time_limit + 12:
            raise TimeoutError("Map failed to terminate at its native game-time limit")

        await session.call([_bot_step(p, c, o, iteration) for p, c, o in zip(players, session.clients, observations)])
        if any(not c.in_game for c in session.clients):
            raise RuntimeError("A bot left the match; independent client resignation is not supported yet")
        steps = [c.game_step for c in session.clients]
        if any(type(s) is not int or not 1 <= s <= 224 for s in steps) or len(set(steps)) != 1:
            raise ValueError("All bots must use the same integer client.game_step in 1..224")
        await session.step(steps[0])
        observations = await session.observe()
        iteration += 1


async def _run_multiplayer_game_async(
    map_settings: Map | str | Path,
    players: Sequence[Bot],
    realtime: bool = False,
    *,
    team_ids: Sequence[int],
    save_replay_as: str | Path | None = None,
    game_time_limit: float = 120,
    random_seed: int | None = None,
    disable_fog: bool = False,
    output_dir: str | Path | None = None,
    step_size: int = 8,
    timeout: float = 90,
    graphics_api: str | None = None,
    window_size: tuple[int, int] | None = None,
    sc2_version=None,
) -> list[Result]:
    """Awaitable equivalent of :func:`run_game`; see its parameter contract."""
    players, team_ids = tuple(players), tuple(team_ids)
    _validate(players, team_ids, realtime, step_size, game_time_limit, timeout, random_seed)
    source = Path(map_settings.path if isinstance(map_settings, Map) else map_settings).resolve()
    scenario = validate_map(source)
    replay = Path(save_replay_as).resolve() if save_replay_as is not None else None
    if replay is not None and replay.exists():
        raise FileExistsError(f"Refusing to overwrite replay: {replay}")
    output = Path(output_dir or Path("reports") / f"game-{uuid4().hex[:12]}").resolve()
    # Reserve the directory atomically; a failed/repeated run cannot erase evidence.
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "starting", "team_ids": team_ids, "player_count": len(players), "source_map": str(source),
              "seed": randbits(32) if random_seed is None else random_seed, "disable_fog": disable_fog,
              "game_time_limit": game_time_limit, "step_size": step_size, "realtime": realtime, "scenario": scenario}
    try:
        prepared = prepare_map(source, output / "game.SC2Map", team_ids, game_time_limit, realtime=realtime)
        async with NativeMultiplayerSession(
            prepared, output=output / "session", players=len(players), seed=report["seed"], disable_fog=disable_fog, timeout=timeout,
            races=[p.race for p in players], names=[p.name or f"MPSC2-bot-{i+1}" for i, p in enumerate(players)],
            raw_affects_selection=[getattr(p.ai, 'raw_affects_selection', None) for p in players],
            realtime=realtime, graphics_api=graphics_api, window_size=window_size,
            **({'sc2_version': sc2_version} if sc2_version is not None else {}),
        ) as session:
            report["players"] = [
                {"index": i, "player_id": pid, "team_id": team_ids[i], "name": players[i].name,
                 "race": players[i].race.name, **session.native_metadata["processes"][i]}
                for i, pid in enumerate(session.player_ids)
            ]
            observations, report["setup"] = await _configure_teams(session, team_ids, scenario)
            for client in session.clients:
                client.game_step = step_size
            await session.call([
                _initialize_bot(p.ai, c, pid, o, i, team_ids, session.player_ids, realtime, scenario)
                for i, (p, c, pid, o) in enumerate(zip(players, session.clients, session.player_ids, observations))
            ])
            play = _play_realtime if realtime else _play
            results = await play(session, players, observations, game_time_limit, report)
            if replay is not None:
                await session.save_replay(replay)
                report["replay"] = str(replay)
            await session.call([p.ai.on_end(result) for p, result in zip(players, results)])
            report.update(status="completed", results=[r.name for r in results])
            return results
    except BaseException as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        (output / "result.json").write_text(json.dumps(report, indent=2) + "\n")


async def play_from_websocket(ws_connection, player, realtime, portconfig,
                              save_replay_as=None, game_time_limit=None, should_close=True):
    """Upstream ladder/external-lobby entry point (standard games only).

    It does not initialize multiplayer alliances or the native bridge.
    Use run_game_async for MPSC2-managed multiplayer scenarios.
    """
    from sc2.main import play_from_websocket as upstream
    return await upstream(ws_connection, player, realtime, portconfig,
                          save_replay_as, game_time_limit, should_close)


async def run_match(controllers, match, close_ws=True):
    """Upstream externally managed standard match; multiplayer scenarios own their processes."""
    from dataclasses import replace
    from sc2.main import run_match as upstream
    if len(match.players) > 2 or getattr(match, 'team_ids', None) is not None:
        raise NotImplementedError('Use run_multiple_games_async for multiplayer matches with fresh sessions')
    if any(getattr(match, name, default) != default for name, default in {
        'save_replay_as': None, 'output_dir': None, 'step_size': 8, 'timeout': 90,
        'graphics_api': None, 'window_size': None,
    }.items()):
        raise NotImplementedError('Externally managed matches accept upstream GameMatch options only')
    return await upstream(controllers, replace(match, map_sc2=_standard_map(match.map_sc2)), close_ws)


# Match the familiar sc2.main import location as well as the top-level API.
from .matches import GameMatch, run_multiple_games, run_multiple_games_async, a_run_multiple_games
from .replay import run_replay, run_replay_async, get_replay_version
