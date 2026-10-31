"""Replay playback and analysis using python-sc2's Controller and Client.

Replay stepping is explicit even when realtime=True: this means wall-clock
playback pacing, avoiding the engine's stalled native realtime replay path.
"""
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, contextmanager
import json
import math
from pathlib import Path
import platform
import re
from tempfile import TemporaryDirectory
import time

import mpyq
from sc2.client import Client
from sc2.data import Race, Result, race_townhalls
from sc2.position import Point2
from s2clientprotocol import sc2api_pb2 as api

from .session import OwnedSC2Process, barrier


@contextmanager
def _observer_callbacks(ai):
    """Supply four callbacks missing from upstream 7.3.0's ObserverAI.

    Bind upstream's no-op defaults only to this replay instance, preserving
    user overrides and restoring it even when playback fails.
    """
    from sc2.bot_ai import BotAI
    added = []
    try:
        if ai is not None:
            for name in ('on_unit_took_damage', 'on_unit_type_changed',
                         'on_enemy_unit_entered_vision', 'on_enemy_unit_left_vision'):
                if not hasattr(ai, name):
                    setattr(ai, name, getattr(BotAI, name).__get__(ai, type(ai)))
                    added.append(name)
        yield
    finally:
        for name in added:
            delattr(ai, name)


def get_replay_version(replay_path):
    archive = mpyq.MPQArchive(str(Path(replay_path)), listfile=False)
    try:
        metadata = json.loads(archive.read_file('replay.gamemetadata.json'))
    finally:
        archive.file.close()
    build, data = metadata['BaseBuild'], metadata['DataVersion']
    if not re.fullmatch(r'Base\d+', build) or not re.fullmatch(r'[0-9A-Fa-f]{32}', data):
        raise ValueError('Replay has invalid build/data-version metadata')
    return build, data


def _prepare_observer(ai, observation, info):
    from .main import _game_state
    observer = ai.race == Race.NoRace
    # burnysc2 7.3.0 indexes race_townhalls[NoRace], which is absent. Adapt only
    # this observer's synchronous classification; never mutate upstream globals.
    if observer:
        ai.race = Race.Terran
    try:
        ai._prepare_step(_game_state(observation), info)
        if observer:
            ai.townhalls = ai.structures.of_type(set().union(*race_townhalls.values()))
    finally:
        if observer:
            ai.race = Race.NoRace


async def _play(client, ai, observed_id, realtime, speed, timeout, max_game_loop):
    async def call(awaitable):
        return (await barrier([awaitable], timeout, [client]))[0]

    first = await call(client.observation())
    game_info = await call(client.get_game_info())
    if observed_id and observed_id not in game_info.player_races:
        raise ValueError(f'Player {observed_id} is absent from this replay')
    if ai is not None:
        ai._initialize_variables()
        game_data = await call(client.get_game_data())
        ping = await call(client.ping())
        ai._prepare_start(client, observed_id, game_info, game_data, realtime=realtime, base_build=ping.ping.base_build)
        ai.observed_player_id = observed_id
        info = await call(client._execute(game_info=api.RequestGameInfo()))
        _prepare_observer(ai, first, info)
        ai._prepare_first_step()
        await call(ai.on_start())
    # A useful initial viewpoint, while leaving subsequent camera control to the user/observer.
    if ai is None:
        await call(client.obs_move_camera(Point2(game_info.map_center), distance=40))
    start_loop = first.observation.observation.game_loop
    started = time.monotonic()
    observation, iteration = first, 0
    while True:
        results = {p.player_id: Result(p.result) for p in observation.observation.player_result}
        frame = observation.observation.observation.game_loop
        if results or (max_game_loop is not None and frame >= max_game_loop):
            if ai is not None:
                await call(ai.on_end(results.get(observed_id)))
            return results
        if ai is not None:
            info = await call(client._execute(game_info=api.RequestGameInfo()))
            _prepare_observer(ai, observation, info)
            await call(ai.issue_events())
            await call(ai.on_step(iteration))
            await call(ai._after_step())
        if type(client.game_step) is not int or not 1 <= client.game_step <= 224:
            raise ValueError('Replay client.game_step must be in 1..224')
        count = client.game_step
        if max_game_loop is not None:
            count = min(count, max_game_loop - frame)
        if realtime:
            await asyncio.sleep(max(0, started + (frame-start_loop+count)/(22.4*speed) - time.monotonic()))
        await call(client.step(count))
        observation = await call(client.observation())
        if observation.observation.observation.game_loop <= frame and not observation.observation.player_result:
            raise RuntimeError('Replay did not advance after a step request')
        iteration += 1


async def run_replay_async(ai, replay_path, realtime=False, observed_id=0, *,
                           speed=1.0, step_size=4, timeout=90, max_game_loop=None,
                           graphics_api=None, window_size=(1280, 800)):
    """Run an ObserverAI (or None for viewing); return native player->Result.

    on_end receives the selected player's Result, or None for an all-player
    observer / bounded preview. A preview returns {}, never fabricated results.
    Closing/cancelling playback releases only this replay's SC2 process.
    """
    from sc2.observer_ai import ObserverAI
    path = Path(replay_path).expanduser().resolve(strict=True)
    if ai is not None and not isinstance(ai, ObserverAI):
        raise TypeError('ai must be an sc2/mpsc2 ObserverAI instance or None')
    if type(realtime) is not bool or type(observed_id) is not int or not 0 <= observed_id <= 16:
        raise ValueError('realtime must be bool and observed_id an integer in 0..16')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in (speed, timeout)):
        raise ValueError('speed and timeout must be finite positive numbers')
    if type(step_size) is not int or not 1 <= step_size <= 224:
        raise ValueError('step_size must be an integer in 1..224')
    if max_game_loop is not None and (type(max_game_loop) is not int or max_game_loop < 1):
        raise ValueError('max_game_loop must be a positive integer or None')
    if not isinstance(window_size, (tuple, list)) or len(window_size) != 2 or any(type(v) is not int or v <= 0 for v in window_size):
        raise ValueError('window_size must contain two positive integers')
    if graphics_api is not None and (not isinstance(graphics_api, str) or not graphics_api):
        raise ValueError('graphics_api must be a nonempty string or None')
    build, data = get_replay_version(path)
    graphics_api = graphics_api or ('Metal' if platform.system() == 'Darwin' else None)
    async with AsyncExitStack() as stack:
        if platform.system() == 'Darwin' and build == 'Base96883' and observed_id >= 4:
            # The same 3-player_id lookup also crashes selected-player replays.
            # IDs 0..3 do not underflow; other builds keep their upstream path.
            import os
            from .native_session import (NativeProcess, build_observation_guard,
                                         observation_guard_environment, validate_executable)
            root = Path(os.environ.get('SC2PATH', '/Applications/StarCraft II')).expanduser().resolve()
            executable = root / 'Versions' / build / 'SC2.app/Contents/MacOS/SC2'
            validate_executable(executable)
            output = Path(stack.enter_context(TemporaryDirectory(prefix='mpsc2-replay-')))
            helper = build_observation_guard(output)
            env = {k: v for k, v in os.environ.items() if not k.startswith('MPSC2_') and k != 'DYLD_INSERT_LIBRARIES'}
            process = NativeProcess(executable, root, output,
                observation_guard_environment(env, helper, output), 0, resolution=window_size)
            process._arguments['-dataVersion'] = data
        else:
            process = OwnedSC2Process(fullscreen=False, resolution=window_size, base_build=build, data_hash=data)
        if graphics_api:
            process._arguments['-graphicsapi'] = graphics_api
        controller = await asyncio.wait_for(stack.enter_async_context(process), timeout)
        # The public upstream functions are used; the observer loop above fixes
        # the NoRace classification and absent player-zero result in 7.3.0.
        await barrier([controller.start_replay(str(path), realtime=False, observed_id=observed_id)], timeout, [controller])
        client = Client(controller._ws)
        client.game_step = step_size
        with _observer_callbacks(ai):
            return await _play(client, ai, observed_id, realtime, speed, timeout, max_game_loop)


def run_replay(ai, replay_path, realtime=False, observed_id=0, **kwargs):
    from .main import _sync
    return _sync(run_replay_async(ai, replay_path, realtime, observed_id, **kwargs), 'run_replay_async')
