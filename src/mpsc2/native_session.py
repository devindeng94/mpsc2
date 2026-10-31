"""Experimental 2..8-client python-sc2 session for the pinned macOS SC2 build.

Each agent has its own SC2 process, WebSocket, Client and native player ID. The
host-only bridge supplies missing local-lobby initialization/discovery behavior;
a separate process-local observation guard removes a 1v1-only upgrade lookup.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
from types import SimpleNamespace

from sc2.client import Client
from sc2.data import Race
from sc2.portconfig import Portconfig
from s2clientprotocol import sc2api_pb2 as api

from .session import MultiplayerSession, OwnedSC2Process

BUILD = "96883"
EXECUTABLE_SHA256 = "7a8e076ce304d6cc18591eed03bda5ea68a8639826c0b7364de3f53a3da8e0eb"


def require_native_platform():
    if platform.system() != "Darwin":
        raise RuntimeError(
            f"No native multiplayer backend for {platform.system()}. Bundled 2–8-client scenarios "
            "require macOS Base96883. Run 'python -m mpsc2 doctor --mode standard' for "
            "upstream one/two-player games, or 'python -m mpsc2.probe' for engine diagnostics."
        )


def validate_executable(executable: Path):
    require_native_platform()
    actual = hashlib.sha256(executable.read_bytes()).hexdigest()
    if actual != EXECUTABLE_SHA256:
        raise RuntimeError(f"Unsupported SC2 executable SHA256 {actual}; refusing native bridge")


def build_bridge(output: Path) -> Path:
    source = Path(__file__).parent / "native/local_four_bridge.c"
    target = output / "local_four_bridge.dylib"
    command = ["clang", "-arch", "x86_64", "-dynamiclib", "-O2", "-Wall", "-Wextra", str(source), "-o", str(target)]
    result = subprocess.run(command, text=True, capture_output=True, timeout=60)
    (output / "bridge-build.log").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f"Bridge compilation failed: {result.stderr}")
    return target.resolve()


def build_observation_guard(output: Path) -> Path:
    source = Path(__file__).parent / 'native/observation_guard.c'
    target = output / 'observation_guard.dylib'
    command = ['clang', '-arch', 'x86_64', '-dynamiclib', '-O2', '-Wall', '-Wextra', str(source), '-o', str(target)]
    result = subprocess.run(command, text=True, capture_output=True, timeout=60)
    (output / 'observation-guard-build.log').write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f'Observation guard compilation failed: {result.stderr}')
    return target.resolve()


def observation_guard_environment(env: dict, helper: Path, output: Path) -> dict:
    """Scope the guard to one explicitly owned process without changing os.environ."""
    previous = env.get('DYLD_INSERT_LIBRARIES')
    return {**env, 'DYLD_INSERT_LIBRARIES': str(helper) + (':' + previous if previous else ''),
            'MPSC2_OBSERVATION_GUARD_LOG': str(output / 'observation-guard.json')}


async def wait_record(directory: Path, name: str, timeout: float, process=None):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        error = directory / "bridge-error.json"
        if error.exists():
            raise RuntimeError(error.read_text())
        path = directory / name
        if path.exists():
            return json.loads(path.read_text())
        if process is not None and process.poll() is not None:
            raise RuntimeError(f"SC2 process exited while waiting for {name}: {process.returncode}")
        await asyncio.sleep(0.02)
    raise TimeoutError(f"Native bridge did not produce {name} within {timeout}s")


class NativeProcess(OwnedSC2Process):
    def __init__(self, executable: Path, root: Path, output: Path, env: dict, index: int,
                 resolution=(640, 480), graphics_api=None):
        super().__init__(host="127.0.0.1", fullscreen=False, resolution=resolution,
                         placement=(40 + index % 2 * 640, 40 + index // 2 * 480))
        if graphics_api:
            self._arguments["-graphicsapi"] = graphics_api
        self._serverhost = "127.0.0.1"
        self.executable, self.root, self.output, self.env = executable, root, output, env
        self.log = None

    async def _connect(self):
        if 'MPSC2_OBSERVATION_GUARD_LOG' in self.env:
            guarded = await wait_record(self.output, 'observation-guard.json', 65, self._process)
            if not guarded.get('applied'):
                raise RuntimeError(f'Observation guard refused startup: {guarded.get("error")}')
            if guarded.get('pid') != self._process.pid:
                raise RuntimeError('Observation guard report belongs to another process')
            self.observation_guard = guarded
        return await super()._connect()

    def _launch(self):
        self.output.mkdir(parents=True, exist_ok=True)
        command = [str(self.executable), "-listen", "127.0.0.1", "-port", str(self._port),
                   "-dataDir", str(self.root), "-tempDir", self._tmp_dir, "-verbose"]
        for key, value in self._arguments.items():
            command.extend([key, value])
        (self.output / "launch.json").write_text(json.dumps(command, indent=2) + "\n")
        self.log = (self.output / "engine.log").open("wb")
        return subprocess.Popen(command, env=self.env, stdout=self.log, stderr=subprocess.STDOUT)

    def _clean(self):
        try:
            super()._clean()
        finally:
            if self.log:
                self.log.close()


class NativeMultiplayerSession(MultiplayerSession):
    """Independent python-sc2 Clients with a local, build-specific bridge.

    Alliances are set by the map. Guest IDs are assigned
    by connection order, so always use player_ids rather than process indices.
    With realtime=True the engine advances automatically; step() is unavailable.
    """
    def __init__(self, map_path: Path, *, output: Path, players=4, seed=1, disable_fog=False, timeout=90,
                 render_size: tuple[int, int] | None = None, graphics_api: str | None = None,
                 window_size: tuple[int, int] | None = None, races=None, names=None, realtime=False,
                 raw_affects_selection=None):
        if type(players) is not int or not 2 <= players <= 8:
            raise ValueError('Expected 2..8 independent players')
        super().__init__(map_path, players=players, seed=seed, disable_fog=disable_fog, timeout=timeout)
        self.output = output.resolve()
        self.bridge_dir = self.output / "bridge"
        self.native_metadata = {}
        self.render_size = render_size
        self.graphics_api = graphics_api
        self.window_size = window_size
        if type(realtime) is not bool:
            raise ValueError("realtime must be a bool")
        self.realtime = realtime
        self.races = tuple(races) if races is not None else (Race.Terran,) * players
        self.names = tuple(names) if names is not None else tuple(f"MPSC2-agent-{i}" for i in range(players))
        self.raw_affects_selection = tuple(raw_affects_selection) if raw_affects_selection is not None else (None,) * players
        if len(self.raw_affects_selection) != players or any(v is not None and type(v) is not bool for v in self.raw_affects_selection):
            raise ValueError(f'Expected {players} raw_affects_selection flags (bool or None)')
        if len(self.races) != players or any(r not in (Race.Terran, Race.Zerg, Race.Protoss, Race.Random) for r in self.races):
            raise ValueError(f"Expected {players} playable races")
        if len(self.names) != players or any(n is not None and not isinstance(n, str) for n in self.names):
            raise ValueError(f"Expected {players} player names (strings or None)")

    async def __aenter__(self):
        # Refuse before the try/finally report writer can touch prior evidence.
        if self.bridge_dir.exists() or (self.output / "native-session.json").exists():
            raise FileExistsError(f"Use a fresh output directory: {self.output} already contains a native session")
        require_native_platform()
        host_task = None
        try:
            root = Path(os.environ.get("SC2PATH", "/Applications/StarCraft II")).resolve()
            executable = root / f"Versions/Base{BUILD}/SC2.app/Contents/MacOS/SC2"
            validate_executable(executable)
            self.bridge_dir.mkdir(parents=True)
            helper = build_bridge(self.bridge_dir) if self.players > 2 else None
            observation_helper = build_observation_guard(self.bridge_dir) if self.players > 2 else None
            self.ports = Portconfig(guests=self.players-1)
            self.native_metadata = {
                "executable": str(executable), "executable_sha256": EXECUTABLE_SHA256,
                "helper_sha256": hashlib.sha256(helper.read_bytes()).hexdigest() if helper else None,
                "helper_source_sha256": hashlib.sha256((Path(__file__).parent / "native/local_four_bridge.c").read_bytes()).hexdigest(),
                "server_ports": self.ports.server, "guest_ports": self.ports.players,
                "processes": [], "realtime": self.realtime, "player_count": self.players,
                "bridge_required": self.players > 2,
                "observation_guard_required": self.players > 2,
                "observation_guard_source_sha256": hashlib.sha256((Path(__file__).parent / 'native/observation_guard.c').read_bytes()).hexdigest() if observation_helper else None,
            }
            env = {k: v for k, v in os.environ.items() if not k.startswith("MPSC2_") and k != "DYLD_INSERT_LIBRARIES"}
            host_env = {**env, "DYLD_INSERT_LIBRARIES": str(helper),
                        "MPSC2_BRIDGE_DIR": str(self.bridge_dir),
                        "MPSC2_PLAYER_COUNT": str(self.players),
                        "MPSC2_DISCOVERY_PORTS": ",".join(str(p[0]) for p in self.ports.players)}
            for i in range(self.players):
                print(f"Starting independent SC2 client {i + 1}/{self.players}", flush=True)
                process_env = host_env if i == 0 and helper else env
                if observation_helper:
                    process_env = observation_guard_environment(process_env, observation_helper, self.output / f'client-{i}')
                process = NativeProcess(executable, root, self.output / f"client-{i}", process_env, i,
                                        resolution=self.window_size or self.render_size or (640, 480),
                                        graphics_api=self.graphics_api)
                self.processes.append(process)
                controller = await asyncio.wait_for(self.stack.enter_async_context(process), self.timeout)
                self.controllers.append(controller)
                self.clients.append(RecordedClient(controller._ws, self.output / f"client-{i}/api.jsonl",
                                                   render_size=self.render_size))
                if self.raw_affects_selection[i] is not None:
                    self.clients[-1].raw_affects_selection = self.raw_affects_selection[i]
                self.native_metadata["processes"].append({"pid": process._process.pid, "api_port": process._port,
                    "observation_guard": getattr(process, 'observation_guard', None)})
            request = api.RequestCreateGame(local_map=api.LocalMap(map_path=str(self.map_path)),
                                            realtime=self.realtime, random_seed=self.seed, disable_fog=self.disable_fog)
            for _ in range(self.players):
                request.player_setup.add(type=api.Participant)
            response = (await self.call([self.controllers[0]._execute(create_game=request)]))[0]
            self.native_metadata["stock_create_error"] = {
                "code": response.create_game.error if response.create_game.HasField("error") else None,
                "details": response.create_game.error_details}
            if self.players == 2:
                if response.create_game.HasField('error'):
                    raise RuntimeError(f'Stock two-player CreateGame failed: {response.create_game}')
                self.player_ids = await self.call([
                    c.join_game(name=self.names[i], race=self.races[i], portconfig=self.ports)
                    for i, c in enumerate(self.clients)
                ])
                if set(self.player_ids) != {1, 2}:
                    raise RuntimeError(f'Invalid native player IDs: {self.player_ids}')
                self.native_metadata['player_ids'] = self.player_ids
                self.native_metadata['readiness'] = {'native_ready_players': 2, 'stock_api': True}
                print(f'{self.players} native participants joined: {self.player_ids}', flush=True)
                return self
            if (not response.create_game.HasField("error") or response.create_game.error != api.ResponseCreateGame.InvalidPlayerSetup
                    or response.create_game.error_details != "Only 1v1 is supported when using multiple agents"):
                raise RuntimeError("Unexpected CreateGame response; refusing native state transition")
            (self.bridge_dir / "promote.signal").write_text(f"{self.players}-participant-response-complete\n")
            promotion = await wait_record(self.bridge_dir, "promote.json", 10, self.processes[0]._process)
            self.native_metadata["promotion"] = promotion
            if not promotion.get("promoted"):
                raise RuntimeError("Native bridge rejected host preconditions")
            ping = (await self.call([self.clients[0].ping()]))[0]
            if ping.status != api.init_game:
                raise RuntimeError("Promoted host did not enter init_game")
            host_task = asyncio.create_task(self.clients[0].join_game(name=self.names[0], race=self.races[0],
                                                                    portconfig=self.ports))
            await wait_record(self.bridge_dir, "held.json", 20, self.processes[0]._process)
            # Each guest must use its own local pair; sending all pairs to every
            # guest makes this engine reuse the first pair and collide.
            async def host_result():
                return await host_task
            self.player_ids = await self.call([host_result(), *[
                client.join_game(name=self.names[i], race=self.races[i],
                                 portconfig=SimpleNamespace(server=self.ports.server, players=[self.ports.players[i-1]]))
                for i, client in enumerate(self.clients) if i
            ]])
            self.native_metadata["readiness"] = await wait_record(self.bridge_dir, "players-ready.json", 5)
            if set(self.player_ids) != set(range(1, self.players + 1)):
                raise RuntimeError(f"Expected {self.players} distinct player IDs, got {self.player_ids}")
            self.native_metadata["player_ids"] = self.player_ids
            print(f"{self.players} native participants joined: {self.player_ids}", flush=True)
            return self
        except BaseException:
            await self.close()
            if host_task is not None:
                if not host_task.done():
                    host_task.cancel()
                await asyncio.gather(host_task, return_exceptions=True)
            raise
        finally:
            self.output.mkdir(parents=True, exist_ok=True)
            (self.output / "native-session.json").write_text(json.dumps(self.native_metadata, indent=2) + "\n")

    async def step(self, count: int = 8):
        if self.realtime:
            raise RuntimeError("SC2 advances automatically in realtime mode; do not call step()")
        return await super().step(count)


class NativeFourSession(NativeMultiplayerSession):
    """Backward-compatible four-player session; use NativeMultiplayerSession for other counts."""

    def __init__(self, map_path, **kwargs):
        super().__init__(map_path, players=4, **kwargs)


class RecordedClient(Client):
    """Small request/status journal, including the last known simulation frame."""
    def __init__(self, ws, journal, *, render_size=None):
        super().__init__(ws)
        self.journal = journal
        self.render_size = render_size

    async def _execute(self, **kwargs):
        # Capture the engine's RGB frames without python-sc2's interactive
        # pygame renderer. Each independent process supplies its own image.
        if "join_game" in kwargs and self.render_size:
            render = kwargs["join_game"].options.render
            render.resolution.x, render.resolution.y = self.render_size
            render.minimap_resolution.x = render.minimap_resolution.y = 128
            render.width = 44
        entry = {"request": next(iter(kwargs))}
        if "join_game" in kwargs:
            entry["raw_affects_selection"] = kwargs["join_game"].options.raw_affects_selection
        if "observation" in kwargs and kwargs["observation"].HasField("game_loop"):
            entry["requested_game_loop"] = kwargs["observation"].game_loop
        try:
            response = await super()._execute(**kwargs)
            entry["status"] = api.Status.Name(response.status)
            if response.HasField("observation"):
                entry["game_loop"] = response.observation.observation.game_loop
                entry["player_id"] = response.observation.observation.player_common.player_id
                entry["results"] = {p.player_id: p.result for p in response.observation.player_result}
            return response
        except Exception as exc:
            entry["error"] = str(exc)
            entry["status"] = str(self._status)
            raise
        finally:
            with self.journal.open("a") as f:
                f.write(json.dumps(entry) + "\n")
