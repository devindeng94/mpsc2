"""Optional BotAI runner using only public service endpoints for gameplay."""
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from pathlib import Path
from sc2.player import Bot
from sc2.bot_ai import BotAI
from sc2.protocol import ProtocolError
from s2clientprotocol import sc2api_pb2 as api
from ..main import _initialize_bot, _bot_step, _terminal_results
from . import multiplayer_pb2 as pb
from .client import ControlClient, sc2_client
from .contract import require, validate_spec


async def play_botais(control: ControlClient, specification, players, *, save_replay_as=None):
    """Prepare, start, run and close a match using ordinary sc2.player.Bot objects.

    This opt-in runner preserves BotAI callbacks and native action acknowledgments.
    Joint turns intentionally use a separate policy contract. The controller must
    already be authenticated. Each BotAI receives a different proxy/client.
    """
    validate_spec(specification)
    players = list(players)
    require(specification.transport == pb.TRANSPORT_SC2_COMPAT, 'BotAI requires SC2 compatibility transport')
    require(len(players) == len(specification.players) and all(isinstance(p, Bot) and isinstance(p.ai, BotAI) for p in players),
            'One BotAI per agent slot required')
    require(len({id(p.ai) for p in players}) == len(players), 'BotAI objects must be independent')
    require(all(p.race.value == s.race and s.kind == pb.PLAYER_AGENT for p, s in zip(players, specification.players)),
            'Bot races/kinds must match specification')
    replay = Path(save_replay_as) if save_replay_as is not None else None
    if replay is not None and replay.exists():
        raise FileExistsError(replay)
    prepared = await control.prepare(specification)
    try:
        snapshot = await control.start(prepared)
        pids = [p.native_player_id for p in snapshot.players]
        teams = [p.team_id for p in specification.players]
        realtime = specification.clock == pb.CLOCK_REALTIME
        scenario = specification.map.rules_contract.split('.')[1]
        async with AsyncExitStack() as stack:
            clients = [await stack.enter_async_context(sc2_client(prepared, p.slot_id)) for p in prepared.players]
            observations = await asyncio.gather(*(c.observation() for c in clients))
            await asyncio.gather(*(_initialize_bot(p.ai, c, pid, o, i, teams, pids, realtime, scenario)
                                  for i, (p, c, pid, o) in enumerate(zip(players, clients, pids, observations))))
            if realtime:
                async def play_one(player, client, observation):
                    iteration = 0
                    while not observation.observation.player_result:
                        try:
                            await _bot_step(player, client, observation, iteration)
                        except ProtocolError as exc:
                            if not exc.is_game_over_error:
                                raise
                            observation = await client.observation()
                            if not observation.observation.player_result:
                                raise
                            break
                        observation = await client.observation(observation.observation.observation.game_loop + client.game_step)
                        iteration += 1
                    return observation
                observations = await asyncio.gather(*(play_one(p, c, o) for p, c, o in zip(players, clients, observations)))
            else:
                iteration = 0
                while _terminal_results(observations, pids) is None:
                    await asyncio.gather(*(_bot_step(p, c, o, iteration) for p, c, o in zip(players, clients, observations)))
                    require(all(c.game_step == specification.step_count for c in clients), 'Bot changed negotiated step_count')
                    await asyncio.gather(*(c.step(specification.step_count) for c in clients))
                    observations = await asyncio.gather(*(c.observation() for c in clients))
                    iteration += 1
            results = _terminal_results(observations, pids)
            require(results is not None, 'Native terminal results missing')
            if replay is not None:
                response = await clients[0]._execute(save_replay=api.RequestSaveReplay())
                require(bool(response.save_replay.data), 'Engine returned an empty replay')
                replay.parent.mkdir(parents=True, exist_ok=True)
                with replay.open('xb') as file:
                    file.write(response.save_replay.data)
            await asyncio.gather(*(p.ai.on_end(r) for p, r in zip(players, results)))
            await control.close_match(prepared)
            return results
    finally:
        await control.close_match(prepared)
