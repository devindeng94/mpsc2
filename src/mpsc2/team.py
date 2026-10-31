"""Team metadata and visible allied-unit helpers for existing BotAI policies."""
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from sc2.units import Units


@dataclass(frozen=True)
class TeamInfo:
    player_id: int
    player_index: int
    team_id: int
    team_ids: Mapping[int, int]

    def __post_init__(self):
        object.__setattr__(self, 'team_ids', MappingProxyType(dict(self.team_ids)))

    @property
    def ally_player_ids(self) -> tuple[int, ...]:
        return tuple(p for p, team in self.team_ids.items() if p != self.player_id and team == self.team_id)

    @property
    def enemy_player_ids(self) -> tuple[int, ...]:
        return tuple(p for p, team in self.team_ids.items() if team != self.team_id)


def allied_units(ai, *, structures: bool = False) -> Units:
    """Currently visible allied units (or structures); never owned/hidden units."""
    return ai.all_units.filter(lambda unit: unit.alliance == 2 and unit.is_structure == structures)


__all__ = ['TeamInfo', 'allied_units']
