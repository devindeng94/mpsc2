"""One python-sc2 client/process per agent, with explicit lockstep barriers."""
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Awaitable

from s2clientprotocol import sc2api_pb2 as sc_pb
from sc2.client import Client
from sc2.controller import Controller
from sc2.data import Race
from sc2.portconfig import Portconfig
from sc2.sc2process import SC2Process


class SC2LaunchError(RuntimeError):
    """An owned engine exited before its API connection was established."""

    def __init__(self, process):
        self.pid = process.pid
        self.returncode = process.returncode
        args = process.args
        self.executable = str(args[0]) if isinstance(args, (list, tuple)) and args else str(args)
        super().__init__(
            f'SC2 process {self.pid} exited with code {self.returncode} before its API became available '
            f'({self.executable}). Check the engine startup log and SC2 installation/version; '
            'no game was created.'
        )


class OwnedSC2Process(SC2Process):
    """Scope cleanup to this session, avoiding upstream's global KillSwitch."""

    async def _connect(self):
        # Upstream retries for 180 seconds even when the child has already died.
        # Keep its WebSocket behavior, but watch the specific child we launched.
        connection = asyncio.create_task(super()._connect())
        try:
            while True:
                done, _ = await asyncio.wait({connection}, timeout=0.1)
                if done:
                    return connection.result()
                if self._process is None:
                    raise RuntimeError('SC2 process was cleaned up before API connection')
                if self._process.poll() is not None:
                    raise SC2LaunchError(self._process)
        finally:
            if not connection.done():
                connection.cancel()
            await asyncio.gather(connection, return_exceptions=True)

    async def __aenter__(self):
        try:
            self._process = self._launch()
            self._ws = await self._connect()
            return Controller(self._ws, self)
        except BaseException:
            try:
                await self._close_connection()
            finally:
                self._clean()
            raise

    async def __aexit__(self, *exc):
        try:
            await self._close_connection()
        finally:
            self._clean()


async def barrier(awaitables: list[Awaitable], timeout: float | None, clients=()):
    """Drain all requests before returning; close sockets before timeout cancellation.

    python-sc2's protocol drains outstanding responses when cancelled. Closing
    the sockets first prevents a missing multiplayer peer from hanging cleanup.
    """
    tasks = [asyncio.create_task(a) for a in awaitables]
    try:
        done, pending = await asyncio.wait(tasks, timeout=timeout, return_when=asyncio.FIRST_EXCEPTION)
        errors = [t.exception() for t in done if not t.cancelled() and t.exception() is not None]
        if pending or errors:
            await asyncio.gather(*(c._ws.close() for c in clients), return_exceptions=True)
            for task in pending:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if errors:
                raise errors[0]
            raise TimeoutError(f"Multiplayer barrier timed out after {timeout}s")
        return [t.result() for t in tasks]
    except BaseException:
        await asyncio.gather(*(c._ws.close() for c in clients), return_exceptions=True)
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


class MultiplayerSession:
    """Attempt a local multi-client game; alliance rules belong to the map.

    Stock SC2 5.0.15 rejects four API participants at CreateGame. This launcher
    reports that restriction; NativeFourSession supplies the experimental
    macOS bridge that successfully launches four independent clients.
    Explicit ``api_players=1`` is provided only to diagnose the four-slot map.

    Does not infer player IDs from launch order. ``player_ids`` contains the
    actual IDs returned by JoinGame, in client order.
    """

    def __init__(self, map_path: Path, *, players: int = 4, api_players: int | None = None, seed: int = 1,
                 disable_fog: bool = False, timeout: float = 90):
        if not 2 <= players <= 14:
            raise ValueError("Expected between 2 and 14 participants")
        self.map_path = map_path.resolve()
        if not self.map_path.is_file():
            raise FileNotFoundError(self.map_path)
        self.players = players
        self.api_players = players if api_players is None else api_players
        if not 1 <= self.api_players <= players:
            raise ValueError("API player count must be between 1 and total player count")
        self.seed = seed
        self.disable_fog = disable_fog
        self.timeout = timeout
        self.clients: list[Client] = []
        self.player_ids: list[int] = []
        self.controllers = []
        self.processes = []
        self.ports = None
        self.stack = AsyncExitStack()

    async def __aenter__(self):
        try:
            if self.api_players > 1:
                self.ports = Portconfig(guests=self.api_players - 1)
            for i in range(self.api_players):
                print(f"Starting SC2 instance {i + 1}/{self.api_players}", flush=True)
                process = OwnedSC2Process(fullscreen=False, resolution=(640, 480),
                                     placement=(40 + (i % 2) * 640, 40 + (i // 2) * 480))
                self.processes.append(process)
                controller = await asyncio.wait_for(self.stack.enter_async_context(process), self.timeout)
                self.controllers.append(controller)
                self.clients.append(Client(controller._ws))
            request = sc_pb.RequestCreateGame(
                local_map=sc_pb.LocalMap(map_path=str(self.map_path), map_data=self.map_path.read_bytes()),
                realtime=False, random_seed=self.seed, disable_fog=self.disable_fog,
            )
            for _ in range(self.api_players):
                request.player_setup.add(type=sc_pb.Participant)
            for _ in range(self.players - self.api_players):
                request.player_setup.add(type=sc_pb.Computer, race=Race.Terran.value, difficulty=sc_pb.VeryEasy)
            response = (await self.call([self.controllers[0]._execute(create_game=request)]))[0]
            if response.create_game.HasField("error"):
                raise RuntimeError(f"CreateGame failed: {response.create_game}")
            print("Joining all participants concurrently", flush=True)
            self.player_ids = await self.call([
                client.join_game(name=f"MPSC2-agent-{i + 1}", race=Race.Terran, portconfig=self.ports)
                for i, client in enumerate(self.clients)
            ])
            if len(set(self.player_ids)) != self.api_players or 0 in self.player_ids:
                raise RuntimeError(f"Invalid assigned IDs: {self.player_ids}")
            print(f"Joined player IDs: {self.player_ids}", flush=True)
            return self
        except BaseException:
            await self.close()
            raise

    async def call(self, awaitables):
        return await barrier(awaitables, self.timeout, self.clients)

    async def observe(self):
        return await self.call([client.observation() for client in self.clients])

    async def step(self, count: int = 8):
        if count < 1:
            raise ValueError("Step size must be positive")
        return await self.call([client.step(count) for client in self.clients])

    async def save_replay(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        response = (await self.call([self.clients[0]._execute(save_replay=sc_pb.RequestSaveReplay())]))[0]
        if not response.save_replay.data:
            raise RuntimeError("SC2 returned an empty replay")
        with path.open("xb") as replay:
            replay.write(response.save_replay.data)

    async def close(self):
        # Close the owned processes even after a failed join. No global kill-all.
        try:
            await self.stack.aclose()
        finally:
            if self.ports is not None:
                self.ports.clean()
                self.ports = None

    async def __aexit__(self, *exc):
        await self.close()
