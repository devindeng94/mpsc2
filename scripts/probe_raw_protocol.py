"""Direct SC2 protobuf/WebSocket experiment. No python-sc2 or pysc2 imports.

Run from the repository root:
    .venv/bin/python scripts/probe_raw_protocol.py

Raw .pb request/response frames and JSON summaries are saved for inspection.
Exit 0 only if four distinct participants observe and move their own units.
Exit 1 means experiments completed without that result; 2 means harness failure.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import AsyncExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import aiohttp
from google.protobuf.json_format import MessageToDict
from s2clientprotocol import common_pb2 as common
from s2clientprotocol import sc2api_pb2 as api


def compact_message(message):
    """Keep metadata readable without embedding map/image bytes in JSON."""
    copy = type(message)()
    copy.CopyFrom(message)
    blobs = {}

    def walk(msg, prefix):
        for field, value in list(msg.ListFields()):
            key = prefix + field.name
            if field.type == field.TYPE_BYTES:
                blobs[key] = {"bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
                msg.ClearField(field.name)
            elif field.type == field.TYPE_MESSAGE:
                if field.is_repeated:
                    for i, child in enumerate(value):
                        walk(child, f"{key}[{i}].")
                else:
                    walk(value, key + ".")

    walk(copy, "")
    result = MessageToDict(copy, preserving_proto_field_name=True)
    if blobs:
        result["binary_fields"] = blobs
    return result


class PortPool:
    """Choose distinct local ports usable by TCP and UDP; release before SC2 binds.

    Binding cannot stay reserved while SC2 takes ownership. As with portpicker,
    another local process can race for a released port; such errors are reported.
    """

    def __init__(self):
        self.used = set()

    def pick(self):
        for _ in range(100):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp:
                tcp.bind(("127.0.0.1", 0))
                port = tcp.getsockname()[1]
                if port in self.used:
                    continue
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
                    try:
                        udp.bind(("127.0.0.1", port))
                    except OSError:
                        continue
                self.used.add(port)
                return port
        raise RuntimeError("Could not allocate a distinct TCP/UDP port")

    def network(self, clients):
        return {"server": [self.pick(), self.pick()],
                "clients": [[self.pick(), self.pick()] for _ in range(clients - 1)]}


class RawClient:
    def __init__(self, index, executable, root, output, ports, timeout, *, extra_args=(), process_env=None):
        self.index = index
        self.executable = executable
        self.root = root
        self.output = output / f"client-{index}"
        self.output.mkdir(parents=True, exist_ok=True)
        self.port = ports.pick()
        self.timeout = timeout
        self.proc = None
        self.http = None
        self.ws = None
        self.temp = None
        self.log = None
        self.request_id = 0
        self.lock = asyncio.Lock()
        self.extra_args = tuple(extra_args)
        self.process_env = process_env

    async def __aenter__(self):
        try:
            self.temp = tempfile.TemporaryDirectory(prefix="mpsc2-raw-")
            self.log = (self.output / "engine.log").open("wb")
            args = [str(self.executable), "-listen", "127.0.0.1", "-port", str(self.port),
                    "-dataDir", str(self.root), "-tempDir", self.temp.name,
                    "-displayMode", "0", "-windowwidth", "640", "-windowheight", "480",
                    "-windowx", str(40 + self.index % 2 * 640),
                    "-windowy", str(40 + self.index // 2 * 480), *self.extra_args]
            (self.output / "launch.json").write_text(json.dumps(args, indent=2) + "\n")
            self.proc = subprocess.Popen(args, stdout=self.log, stderr=subprocess.STDOUT, env=self.process_env)
            self.http = aiohttp.ClientSession()
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                if self.proc.poll() is not None:
                    raise RuntimeError(f"SC2 process {self.index} exited with {self.proc.returncode}")
                try:
                    self.ws = await self.http.ws_connect(f"http://127.0.0.1:{self.port}/sc2api",
                                                         max_msg_size=64 * 1024 * 1024)
                    break
                except aiohttp.ClientConnectorError:
                    await asyncio.sleep(0.5)
            if self.ws is None:
                raise TimeoutError(f"SC2 API {self.index} did not start within {self.timeout}s")
            print(f"Raw client {self.index}: process {self.proc.pid}, WebSocket port {self.port}", flush=True)
            return self
        except BaseException:
            await self.close()
            raise

    async def call(self, method, payload, timeout=None):
        async with self.lock:
            self.request_id += 1
            request = api.Request(id=self.request_id, **{method: payload})
            frame = request.SerializeToString()
            stem = self.output / f"{self.request_id:03d}-{method}"
            stem.with_suffix(".request.pb").write_bytes(frame)
            stem.with_suffix(".request.json").write_text(json.dumps(compact_message(request), indent=2) + "\n")

            async def exchange():
                await self.ws.send_bytes(frame)
                return await self.ws.receive_bytes()

            try:
                response_frame = await asyncio.wait_for(exchange(), timeout or self.timeout)
                response = api.Response.FromString(response_frame)
                stem.with_suffix(".response.pb").write_bytes(response_frame)
                stem.with_suffix(".response.json").write_text(json.dumps(compact_message(response), indent=2) + "\n")
                if response.HasField("id") and response.id != request.id:
                    raise RuntimeError(f"Mismatched response id: {response.id} != {request.id}")
                return response
            except BaseException as exc:
                # A timed-out stream can contain an outstanding reply. Never reuse it.
                await self.ws.close()
                if isinstance(exc, asyncio.TimeoutError):
                    raise TimeoutError() from exc
                raise

    async def close(self):
        if self.ws is not None:
            await self.ws.close()
        if self.http is not None:
            await self.http.close()
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                await asyncio.to_thread(self.proc.wait, 5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                await asyncio.to_thread(self.proc.wait, 5)
        if self.log is not None:
            self.log.close()
        if self.temp is not None:
            self.temp.cleanup()

    async def __aexit__(self, *exc):
        await self.close()


def create_request(map_path, types, realtime=False, *, map_bytes=False):
    request = api.RequestCreateGame(local_map=api.LocalMap(map_path=str(map_path.resolve())))
    if map_bytes:
        request.local_map.map_data = map_path.read_bytes()
    if realtime is not None:
        request.realtime = realtime
    for player_type in types:
        player = request.player_setup.add(type=player_type)
        if player_type == api.Computer:
            player.race = common.Terran
            player.difficulty = api.VeryEasy
    return request


def join_request(index, network):
    request = api.RequestJoinGame(race=common.Terran, player_name=f"Raw-{index}",
                                 host_ip="127.0.0.1", options=api.InterfaceOptions(raw=True, score=True))
    request.server_ports.game_port, request.server_ports.base_port = network["server"]
    for game, base in network["clients"]:
        request.client_ports.add(game_port=game, base_port=base)
    return request


def accepted(response, method):
    return (not response.error and response.HasField(method)
            and not getattr(response, method).HasField("error"))


async def start_clients(stack, count, args, output, pool):
    # Sequential context entry guarantees cleanup registration before the next
    # launch. Each connection gets its own process, socket, and request sequence.
    clients = []
    for i in range(count):
        client = RawClient(i, args.executable, args.sc2_root, output, pool, args.timeout)
        clients.append(await stack.enter_async_context(client))
    return clients


async def verify_participants(clients, joins, output):
    ids = [r.join_game.player_id for r in joins]
    if len(set(ids)) != len(clients) or 0 in ids:
        raise AssertionError(f"Not distinct participant IDs: {ids}")
    infos = await asyncio.gather(*(c.call("game_info", api.RequestGameInfo()) for c in clients))
    for info in infos:
        participants = {p.player_id for p in info.game_info.player_info if p.type == api.Participant}
        if participants != set(ids):
            raise AssertionError(f"Roster {participants} does not match assigned participants {ids}")
    await asyncio.gather(*(c.call("step", api.RequestStep(count=8)) for c in clients))
    observations = await asyncio.gather(*(c.call("observation", api.RequestObservation()) for c in clients))
    positions = []
    calls = []
    for client, pid, response in zip(clients, ids, observations):
        obs = response.observation.observation
        if obs.player_common.player_id != pid:
            raise AssertionError("Observation is not the joined player's perspective")
        own = [u for u in obs.raw_data.units if u.owner == pid and u.alliance == 1]
        if not own:
            raise AssertionError(f"No own units for player {pid}")
        positions.append({u.tag: (u.pos.x, u.pos.y) for u in own})
        action = api.Action()
        command = action.action_raw.unit_command
        command.ability_id = 16  # Blizzard stable raw ability: Move.
        command.unit_tags.extend(u.tag for u in own)
        command.target_world_space_pos.x = sum(u.pos.x for u in own) / len(own)
        command.target_world_space_pos.y = sum(u.pos.y for u in own) / len(own) + 4
        calls.append(client.call("action", api.RequestAction(actions=[action])))
    actions = await asyncio.gather(*calls)
    if any(list(r.action.result) != [1] for r in actions):
        raise AssertionError(f"Rejected actions: {[list(r.action.result) for r in actions]}")
    await asyncio.gather(*(c.call("step", api.RequestStep(count=32)) for c in clients))
    observations = await asyncio.gather(*(c.call("observation", api.RequestObservation()) for c in clients))
    loops = [r.observation.observation.game_loop for r in observations]
    if len(set(loops)) != 1 or loops[0] < 40:
        raise AssertionError(f"Step did not synchronize: {loops}")
    moved = {}
    for pid, before, response in zip(ids, positions, observations):
        moved[pid] = sum(abs(u.pos.x - before[u.tag][0]) + abs(u.pos.y - before[u.tag][1]) > 0.25
                        for u in response.observation.observation.raw_data.units if u.tag in before)
        if not moved[pid]:
            raise AssertionError(f"Player {pid} did not move its own units")
    replay = await clients[0].call("save_replay", api.RequestSaveReplay())
    if not replay.save_replay.data:
        raise AssertionError("Empty replay")
    (output / "match.SC2Replay").write_bytes(replay.save_replay.data)
    return {"player_ids": ids, "game_loops": loops, "moved_units": moved,
            "verified_independent_participants": len(ids)}


async def join_attempt(clients, pool, output, timeout, *, guest_ports="shared", host_ready_signal=None, network=None):
    network = pool.network(len(clients)) if network is None else network
    networks = [network if i == 0 or guest_ports == "shared"
                else {"server": network["server"], "clients": [network["clients"][i-1]]}
                for i in range(len(clients))]
    tasks = []
    try:
        tasks.append(asyncio.create_task(clients[0].call("join_game", join_request(0, networks[0]), timeout=timeout)))
        if host_ready_signal is not None:
            for _ in range(200):
                if host_ready_signal.exists():
                    break
                if tasks[0].done():
                    raise RuntimeError("Host join completed before the lobby hold was acknowledged")
                await asyncio.sleep(0.1)
            else:
                raise TimeoutError("Host lobby hold not acknowledged within 20 seconds")
        tasks.extend(asyncio.create_task(c.call("join_game", join_request(i, networks[i]), timeout=timeout))
                     for i, c in enumerate(clients) if i)
        results = await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    entries = [({"transport_error": f"{type(r).__name__}: {r}"} if isinstance(r, BaseException)
                else compact_message(r)) for r in results]
    outcome = {"network_ports": network, "guest_ports": guest_ports,
               "join_responses": entries, "verified_independent_participants": 0}
    if all(not isinstance(r, BaseException) and accepted(r, "join_game") for r in results):
        try:
            outcome.update(await verify_participants(clients, results, output))
        except Exception as exc:
            outcome["verification_error"] = f"{type(exc).__name__}: {exc}"
    else:
        # A partial join is useful evidence but never counted as a successful
        # multiplayer experiment. Inspect its roster to locate the next limit.
        outcome["partial_rosters"] = []
        for i, (client, response) in enumerate(zip(clients, results)):
            if not isinstance(response, BaseException) and accepted(response, "join_game"):
                try:
                    info = await client.call("game_info", api.RequestGameInfo(), timeout=5)
                    outcome["partial_rosters"].append({"client": i, "response": compact_message(info)})
                except Exception as exc:
                    outcome["partial_rosters"].append({"client": i, "error": f"{type(exc).__name__}: {exc}"})
    return outcome


async def experiment(args, report, save):
    pool = PortPool()
    # First phase: four real processes, with direct creation requests to the host.
    output = args.output / "create-matrix"
    async with AsyncExitStack() as stack:
        clients = await start_clients(stack, 4, args, output, pool)
        report["processes"] = [{"pid": c.proc.pid, "api_port": c.port} for c in clients]
        report["pings"] = [compact_message(r) for r in await asyncio.gather(
            *(c.call("ping", api.RequestPing()) for c in clients))]
        save()
        cases = [
            ("four-stepped-path", [api.Participant] * 4, False, False),
            ("four-realtime-path", [api.Participant] * 4, True, False),
            ("four-default-mode", [api.Participant] * 4, None, False),
            ("four-map-bytes", [api.Participant] * 4, False, True),
            ("three-participants", [api.Participant] * 3, False, False),
            ("map-defined-slots-no-setup", [], False, False),
            ("two-participants-two-computers", [api.Participant] * 2 + [api.Computer] * 2, False, False),
        ]
        for name, types, realtime, use_bytes in cases:
            response = await clients[0].call("create_game", create_request(args.map, types, realtime, map_bytes=use_bytes))
            case = {"name": name, "accepted": accepted(response, "create_game"), "response": compact_message(response)}
            report["create_cases"].append(case)
            print(f"{name}: {json.dumps(case['response'])}", flush=True)
            save()
            if case["accepted"]:
                # A four-participant acceptance is immediately pursued through
                # actual joins, observations and commands. Never infer success.
                if len(types) == 4 and all(t == api.Participant for t in types):
                    if realtime:
                        case["note"] = "Realtime CreateGame accepted; stepped verifier is not applicable"
                    else:
                        case["join_test"] = await join_attempt(clients, pool, output, args.join_timeout)
                        if case["join_test"]["verified_independent_participants"] == 4:
                            report["four_players_verified"] = True
                save()
                break  # Accepted CreateGame changes host state; use fresh processes next.
    if report["four_players_verified"]:
        return

    # Valid two-participant control and attempts to obtain four participant joins
    # from a lobby with fewer declared participant slots.
    for name, types, join_count in [
        ("two-client-control", [api.Participant] * 2, 2),
        ("two-declared-four-joiners", [api.Participant] * 2, 4),
        ("one-declared-three-computers-four-joiners", [api.Participant] + [api.Computer] * 3, 4),
    ]:
        output = args.output / name
        async with AsyncExitStack() as stack:
            clients = await start_clients(stack, join_count, args, output, pool)
            response = await clients[0].call("create_game", create_request(args.map, types))
            case = {"name": name, "create_response": compact_message(response)}
            report["join_cases"].append(case)
            save()
            if accepted(response, "create_game"):
                case.update(await join_attempt(clients, pool, output, args.join_timeout))
            print(f"{name}: {json.dumps(case)}", flush=True)
            if case.get("verified_independent_participants") == 4:
                report["four_players_verified"] = True
            save()
        if report["four_players_verified"]:
            return


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", type=Path, default=Path("maps/MPSC2TeamArena.SC2Map"))
    parser.add_argument("--sc2-root", type=Path, default=Path(os.environ.get("SC2PATH", "/Applications/StarCraft II")))
    parser.add_argument("--executable", type=Path, help="Override automatic macOS executable discovery")
    parser.add_argument("--output", type=Path, default=Path("reports/raw-protocol"))
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--join-timeout", type=float, default=30)
    args = parser.parse_args()
    if args.executable is None:
        binaries = list((args.sc2_root / "Versions").glob("Base*/SC2.app/Contents/MacOS/SC2"))
        if not binaries:
            parser.error("SC2 executable not found; specify --executable and --sc2-root")
        args.executable = max(binaries, key=lambda p: int(p.parents[3].name[4:]))
    if not args.map.is_file() or not args.executable.is_file():
        parser.error("Map or SC2 executable does not exist")
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"started_at_utc": datetime.now(timezone.utc).isoformat(),
              "transport": "aiohttp WebSocket + s2clientprotocol protobuf; direct subprocess launch",
              "executable": str(args.executable), "map": str(args.map.resolve()),
              "map_sha256": hashlib.sha256(args.map.read_bytes()).hexdigest(),
              "four_players_verified": False, "create_cases": [], "join_cases": []}

    def save():
        (args.output / "result.json").write_text(json.dumps(report, indent=2) + "\n")

    try:
        asyncio.run(experiment(args, report, save))
        code = 0 if report["four_players_verified"] else 1
    except Exception as exc:
        import traceback
        traceback.print_exc()
        report["harness_error"] = f"{type(exc).__name__}: {exc}"
        code = 2
    finally:
        report["python_sc2_imported"] = any(n == "sc2" or n.startswith("sc2.") for n in sys.modules)
        report["pysc2_imported"] = any(n == "pysc2" or n.startswith("pysc2.") for n in sys.modules)
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        save()
    print(f"Report: {args.output.resolve() / 'result.json'}", flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
