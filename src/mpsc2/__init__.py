"""Multiplayer research extensions for python-sc2 (burnysc2 7.3.0)."""

__version__ = '0.3.1a3'

from .main import run_game, run_game_async
from .matches import GameMatch, run_multiple_games, run_multiple_games_async, a_run_multiple_games
from .replay import run_replay, run_replay_async, get_replay_version
from .team import TeamInfo, allied_units
from .capabilities import get_capabilities
from . import maps

__all__ = [
    'run_game', 'run_game_async', 'GameMatch', 'run_multiple_games',
    'run_multiple_games_async', 'a_run_multiple_games', 'run_replay',
    'run_replay_async', 'get_replay_version', 'TeamInfo', 'allied_units',
    'get_capabilities', 'maps', '__version__',
]
