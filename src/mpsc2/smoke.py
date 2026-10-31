"""Live four-client smoke test. Exit nonzero if any required check fails."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
import traceback

from loguru import logger
from s2clientprotocol import raw_pb2 as raw_pb
from s2clientprotocol import sc2api_pb2 as sc_pb
from sc2.ids.ability_id import AbilityId

from .session import MultiplayerSession


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def team_of(pid: int) -> int:
    if pid not in (1, 2, 3, 4):
        raise ValueError(f"Unknown arena player {pid}")
    return (pid - 1) // 2


def inspect_observation(response, pid: int, *, all_visible=True):
    obs = response.observation.observation
    check(obs.player_common.player_id == pid, "Observation player mismatch")
    counts = Counter()
    for unit in obs.raw_data.units:
        if unit.owner not in (1, 2, 3, 4):
            continue
        expected = raw_pb.Self if unit.owner == pid else (
            raw_pb.Ally if team_of(unit.owner) == team_of(pid) else raw_pb.Enemy)
        check(unit.alliance == expected, f"Player {pid} sees owner {unit.owner} as {unit.alliance}, expected {expected}")
        counts[unit.owner] += 1
    expected_owners = {1, 2, 3, 4} if all_visible else {p for p in range(1, 5) if team_of(p) == team_of(pid)}
    for owner in expected_owners:
        check(counts[owner] == 6, f"Player {pid}: expected six units of owner {owner}, got {counts[owner]}")
    if not all_visible:
        check(not any(counts[owner] for owner in range(1, 5) if team_of(owner) != team_of(pid)),
              f"Player {pid} can see enemies outside initial team vision")
    return {"player_id": pid, "game_loop": obs.game_loop, "units_by_owner": dict(counts)}


async def verify_ownership(session, observations):
    """Commands using allies' unit tags must not grant shared unit control."""
    stops = []
    for response, client, pid in zip(observations, session.clients, session.player_ids):
        action = sc_pb.Action()
        action.action_raw.unit_command.ability_id = AbilityId.STOP_STOP.value
        action.action_raw.unit_command.unit_tags.extend(
            u.tag for u in response.observation.observation.raw_data.units if u.owner == pid)
        stops.append(client._execute(action=sc_pb.RequestAction(actions=[action])))
    await session.call(stops)
    await session.step(16)
    observations = await session.observe()
    before = {u.tag: (u.pos.x, u.pos.y) for response in observations
              for u in response.observation.observation.raw_data.units if u.owner in (1, 2, 3, 4)}
    attempts = []
    for response, client, pid in zip(observations, session.clients, session.player_ids):
        other = [u for u in response.observation.observation.raw_data.units
                 if u.owner in (1, 2, 3, 4) and u.owner != pid]
        check(other, f"Player {pid} has no visible other-owned units for the ownership test")
        action = sc_pb.Action()
        action.action_raw.unit_command.ability_id = AbilityId.MOVE_MOVE.value
        action.action_raw.unit_command.unit_tags.extend(u.tag for u in other)
        action.action_raw.unit_command.target_world_space_pos.x = 100
        action.action_raw.unit_command.target_world_space_pos.y = 90
        attempts.append(client._execute(action=sc_pb.RequestAction(actions=[action])))
    responses = await session.call(attempts)
    await session.step(32)
    observations = await session.observe()
    after = {u.tag: (u.pos.x, u.pos.y) for response in observations
             for u in response.observation.observation.raw_data.units if u.tag in before}
    check(set(before) == set(after), "Units disappeared during the ownership check")
    max_drift = max(abs(x-after[tag][0]) + abs(y-after[tag][1]) for tag, (x, y) in before.items())
    check(max_drift < 0.1, f"Other-owner commands moved units: drift={max_drift}")
    return observations, {"other_owner_units_unchanged": True, "max_position_drift": max_drift,
                          "action_results": [list(r.action.result) for r in responses]}


async def combat_to_terminal(session, observations):
    """Exercise native shared results using ordinary commands on all clients.

    Team A focuses enemy units; team B walks through its firing line. This is a
    deliberately asymmetric test policy, not a measure of self-play strength.
    Unlike debug mutations, these commands are synchronized by the game engine.
    """
    for _ in range(300):
        if all(r.observation.player_result for r in observations):
            return observations
        if not any(r.observation.player_result for r in observations):
            loops = [r.observation.observation.game_loop for r in observations]
            check(len(set(loops)) == 1, f"Active combat simulations diverged: {loops}")
        commands = []
        for response, client, pid in zip(observations, session.clients, session.player_ids):
            units = response.observation.observation.raw_data.units
            own = [u for u in units if u.owner == pid]
            if not own:
                continue
            action = sc_pb.Action()
            command = action.action_raw.unit_command
            command.unit_tags.extend(u.tag for u in own)
            if team_of(pid) == 0:
                command.ability_id = AbilityId.ATTACK_ATTACK.value
                enemies = [u for u in units if u.owner in (3, 4)]
                if enemies:
                    x = sum(u.pos.x for u in own) / len(own)
                    y = sum(u.pos.y for u in own) / len(own)
                    command.target_unit_tag = min(enemies, key=lambda u: (u.pos.x-x)**2+(u.pos.y-y)**2).tag
                else:
                    command.target_world_space_pos.x = 80
                    command.target_world_space_pos.y = 57
            else:
                command.ability_id = AbilityId.MOVE_MOVE.value
                # Alternate destinations to keep movement orders active.
                command.target_world_space_pos.x = 36 if (_ // 16) % 2 == 0 else 60
                command.target_world_space_pos.y = 57
            commands.append(client._execute(action=sc_pb.RequestAction(actions=[action])))
        if commands:
            await session.call(commands)
        await session.step(8)
        observations = await session.observe()
    raise AssertionError("Scripted combat did not reach a shared terminal result within 2400 loops")


async def run(args, report):
    if args.experimental_native_four:
        from .native_session import NativeFourSession
        session = NativeFourSession(args.map, output=args.output, seed=args.seed, disable_fog=not args.fog, timeout=args.timeout)
    else:
        session = MultiplayerSession(args.map, api_players=args.api_players, seed=args.seed, disable_fog=not args.fog,
                                     timeout=args.timeout)
    async with session:
        if args.experimental_native_four:
            report["native_bridge"] = session.native_metadata
        report["player_ids_in_client_order"] = session.player_ids
        check(set(session.player_ids) == set(range(1, args.api_players + 1)), "Map did not assign the required API slots")
        ping = (await session.call([session.clients[0].ping()]))[0].ping
        report["sc2"] = {"game_version": ping.game_version, "base_build": ping.base_build,
                         "data_version": ping.data_version}
        infos = await session.call([c._execute(game_info=sc_pb.RequestGameInfo()) for c in session.clients])
        report["rosters"] = [[{"id": p.player_id, "name": p.player_name, "type": p.type}
                              for p in r.game_info.player_info] for r in infos]
        for info in infos:
            participants = {p.player_id for p in info.game_info.player_info if p.type in (sc_pb.Participant, sc_pb.Computer)}
            check(participants == {1, 2, 3, 4}, f"Unexpected game players: {participants}")
        # Map initialization triggers run on the first simulation frames.
        await session.step(8)
        observations = await session.observe()
        report["initial_observations"] = [inspect_observation(r, pid, all_visible=not args.fog)
                                           for r, pid in zip(observations, session.player_ids)]
        print(f"Verified four game players and alliances from {args.api_players} API perspective(s)", flush=True)
        initial_positions = {}
        commands = []
        for response, client, pid in zip(observations, session.clients, session.player_ids):
            own = [u for u in response.observation.observation.raw_data.units if u.owner == pid]
            initial_positions[pid] = {u.tag: (u.pos.x, u.pos.y) for u in own}
            action = sc_pb.Action()
            command = action.action_raw.unit_command
            command.ability_id = AbilityId.MOVE_MOVE.value
            command.unit_tags.extend(u.tag for u in own)
            command.target_world_space_pos.x = sum(u.pos.x for u in own) / len(own)
            command.target_world_space_pos.y = sum(u.pos.y for u in own) / len(own) + 4
            commands.append(client._execute(action=sc_pb.RequestAction(actions=[action])))
        actions = await session.call(commands)
        report["action_results"] = [list(r.action.result) for r in actions]
        check(all(list(r.action.result) == [1] for r in actions), "A player action was rejected")
        for _ in range(8):
            await session.step(8)
        observations = await session.observe()
        loops = [r.observation.observation.game_loop for r in observations]
        check(len(set(loops)) == 1 and loops[0] >= 72, f"Unsynchronized or stalled game: {loops}")
        report["synchronized_game_loops"] = loops
        moved = {}
        for response, pid in zip(observations, session.player_ids):
            moved[pid] = sum(abs(u.pos.x - initial_positions[pid][u.tag][0]) +
                             abs(u.pos.y - initial_positions[pid][u.tag][1]) > 0.25
                             for u in response.observation.observation.raw_data.units if u.owner == pid)
            check(moved[pid] > 0, f"Player {pid}'s own-unit command did not move any units")
        report["moved_units"] = moved
        print(f"All {args.api_players} API controllers moved their own units; at loop {loops[0]}", flush=True)
        if args.api_players == 4:
            observations, report["ownership_check"] = await verify_ownership(session, observations)
            print("Other-player unit commands did not transfer control", flush=True)
        # Preserve launch/control evidence even if a later terminal check fails.
        await session.save_replay(args.output / "movement.SC2Replay")
        if not args.skip_terminal:
            if args.api_players == 4:
                observations = await combat_to_terminal(session, observations)
                report["terminal_test"] = "ordinary synchronized commands: team A attacks, team B moves"
            else:
                # Debug mutations are only a single-process map diagnostic.
                losing_tags = {u.tag for r in observations for u in r.observation.observation.raw_data.units
                               if u.owner in (3, 4)}
                check(len(losing_tags) == 12, "Missing losing-team units for terminal test")
                await session.call([session.clients[0].debug_kill_unit(list(losing_tags))])
                for _ in range(8):
                    await session.step(8)
                    observations = await session.observe()
                    if all(r.observation.player_result for r in observations):
                        break
                report["terminal_test"] = "single-process debug elimination of team B"
            expected = {1: sc_pb.Victory, 2: sc_pb.Victory, 3: sc_pb.Defeat, 4: sc_pb.Defeat}
            results = [{p.player_id: p.result for p in r.observation.player_result} for r in observations]
            check(all(r == expected for r in results), f"Wrong team results: {results}")
            report["terminal_results_by_client"] = results
            report["terminal_game_loops"] = [r.observation.observation.game_loop for r in observations]
            print("Verified shared team results: Victory, Victory, Defeat, Defeat", flush=True)
        replay = args.output / "smoke.SC2Replay"
        await session.save_replay(replay)
        report["replay"] = str(replay.resolve())
        report["status"] = "passed"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", type=Path, default=Path("maps/MPSC2TeamArena.SC2Map"))
    parser.add_argument("--output", type=Path, default=Path("reports/smoke"))
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--api-players", type=int, choices=(1, 4), default=4,
                        help="4 tests native multi-client support; 1 tests map with three computer slots")
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--fog", action="store_true", help="Use normal fog instead of diagnostic full visibility")
    parser.add_argument("--skip-terminal", action="store_true", help="Only test launch, alliances, and movement")
    parser.add_argument("--experimental-native-four", action="store_true",
                        help="Enable the build-pinned macOS bridge for four independent clients")
    args = parser.parse_args()
    if args.experimental_native_four and args.api_players != 4:
        parser.error("The native four-client bridge requires --api-players 4")
    if args.experimental_native_four and args.output.exists() and any(args.output.iterdir()):
        parser.error("The native bridge requires a fresh output directory; existing evidence was preserved")
    args.output.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    logger.add(str(args.output / "protocol.log"), level="INFO", mode="w")
    report = {"status": "failed", "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "burnysc2": importlib.metadata.version("burnysc2"), "seed": args.seed,
              "map": str(args.map.resolve()), "disable_fog": not args.fog,
              "api_players": args.api_players, "game_players": 4,
              "experimental_native_four": args.experimental_native_four}
    try:
        report["map_sha256"] = hashlib.sha256(args.map.read_bytes()).hexdigest()
        asyncio.run(run(args, report))
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        target = args.output / "result.json"
        target.write_text(json.dumps(report, indent=2) + "\n")
        print(f"Report: {target.resolve()}", flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
