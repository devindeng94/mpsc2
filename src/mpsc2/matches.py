"""Sequential matches with a fresh multiplayer session for each episode."""
from dataclasses import dataclass
from typing import Sequence

from sc2.player import AbstractPlayer


@dataclass
class GameMatch:
    """Upstream GameMatch fields plus multiplayer options; use fresh bot instances."""
    map_sc2: object
    players: Sequence[AbstractPlayer]
    realtime: bool = False
    random_seed: int | None = None
    disable_fog: bool | None = None
    sc2_config: list[dict] | None = None
    game_time_limit: float | None = None
    team_ids: Sequence[int] | None = None
    save_replay_as: object = None
    output_dir: object = None
    step_size: int = 8
    timeout: float = 90
    graphics_api: str | None = None
    window_size: tuple[int, int] | None = None

    @property
    def needed_sc2_count(self):
        return sum(player.needs_sc2 for player in self.players)

    @property
    def host_game_kwargs(self):
        return dict(map_settings=self.map_sc2, players=self.players, realtime=self.realtime,
                    random_seed=self.random_seed, disable_fog=self.disable_fog)


async def run_multiple_games_async(matches):
    """Return one player->Result mapping per match; propagate failures, stop the batch.

    Standard upstream GameMatch objects are also accepted. Process reuse is not
    used for multiplayer: each match gets an isolated session and report folder.
    """
    from .main import run_game_async, _standard_map, _is_multiplayer_map
    from sc2.player import Bot
    results = []
    for match in matches:
        if len({id(p) for p in match.players}) != len(match.players):
            raise ValueError('Each match needs distinct player objects for result mapping')
        native_pair = len(match.players) == 2 and all(isinstance(p, Bot) for p in match.players) and _is_multiplayer_map(match.map_sc2)
        if len(match.players) <= 2 and getattr(match, 'team_ids', None) is None and not native_pair:
            # Preserve upstream batch support for BotProcess and sc2_config.
            from sc2.main import GameMatch as UpstreamMatch, a_run_multiple_games
            if isinstance(match, GameMatch):
                if any((match.output_dir is not None, match.step_size != 8, match.timeout != 90,
                        match.graphics_api is not None, match.window_size is not None, match.save_replay_as is not None)):
                    raise NotImplementedError('Standard batch matches use upstream GameMatch options; use run_game for replay saving')
                match = UpstreamMatch(_standard_map(match.map_sc2), list(match.players), match.realtime,
                                      match.random_seed, match.disable_fog, match.sc2_config, match.game_time_limit)
            else:
                _standard_map(match.map_sc2)
            batch = await a_run_multiple_games([match])
            if len(batch) != 1:
                raise RuntimeError('Upstream batch match did not return a result')
            from sc2.data import Result
            for result in batch[0].values():
                if isinstance(result, BaseException):
                    raise result
                if not isinstance(result, Result):
                    raise RuntimeError(f'Upstream batch match returned an invalid result: {result!r}')
            results.extend(batch)
            continue
        if getattr(match, 'sc2_config', None) is not None:
            raise NotImplementedError('sc2_config is only supported for standard upstream matches')
        kwargs = {name: getattr(match, name, default) for name, default in {
            'team_ids': None, 'save_replay_as': None, 'game_time_limit': None, 'random_seed': None,
            'output_dir': None, 'step_size': 8, 'timeout': 90, 'graphics_api': None, 'window_size': None,
        }.items()}
        values = await run_game_async(match.map_sc2, match.players, match.realtime,
                                      disable_fog=bool(match.disable_fog), **kwargs)
        results.append(dict(zip(match.players, values)))
    return results


def run_multiple_games(matches):
    from .main import _sync
    return _sync(run_multiple_games_async(matches), 'run_multiple_games_async')


a_run_multiple_games = run_multiple_games_async
