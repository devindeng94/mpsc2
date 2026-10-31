"""Async adapter for the pinned upstream standard-game lifecycle."""
import asyncio

from sc2.player import Bot, Human
from sc2.portconfig import Portconfig


async def run_standard_async(game_map, players, realtime, portconfig, replay, limit, rgb, seed, version, fog):
    from sc2.main import _host_game, _join_game
    common = dict(realtime=realtime, portconfig=portconfig,
                  save_replay_as=str(replay) if replay is not None else None,
                  game_time_limit=limit, sc2_version=version)
    participants = [p for p in players if isinstance(p, (Human, Bot))]
    if len(participants) > 1:
        owned_ports = Portconfig() if portconfig is None else None
        common['portconfig'] = owned_ports if owned_ports is not None else portconfig
        try:
            results = await asyncio.gather(
                _host_game(game_map, participants, rgb_render_config=rgb, random_seed=seed, disable_fog=fog, **common),
                _join_game(participants, **common), return_exceptions=True,
            )
            for result in results:
                if isinstance(result, BaseException):
                    raise result
            return results
        finally:
            if owned_ports is not None:
                owned_ports.clean()
    return await _host_game(game_map, list(players), rgb_render_config=rgb, random_seed=seed, disable_fog=fog, **common)
