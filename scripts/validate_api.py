"""Opt-in engine integration: two fresh four-client episodes, then replay analysis.

Run with the installed package, e.g. python scripts/validate_api.py --output reports/api-new.
An optional --replay path additionally checks a full economy replay's structures.
"""
import argparse
import json
from pathlib import Path

from mpsc2 import GameMatch, TeamInfo, allied_units, run_multiple_games, run_replay
from mpsc2.bot_ai import BotAI
from mpsc2.data import Race
from mpsc2.observer_ai import ObserverAI
from mpsc2.player import Bot


class VerifyBot(BotAI):
    async def on_start(self):
        assert isinstance(self.team, TeamInfo)
        assert self.team.player_id == self.player_id
        assert self.team.ally_player_ids == self.ally_player_ids
        assert set(self.enemy_races) == set(self.enemy_player_ids)
        assert allied_units(self).amount == 6 * len(self.ally_player_ids)
        self.ended = False

    async def on_step(self, iteration):
        if self.enemy_units:
            for unit in self.units:
                unit.attack(self.enemy_units.closest_to(unit))

    async def on_end(self, result):
        self.ended = True
        self.result = result


class VerifyObserver(ObserverAI):
    async def on_start(self):
        self.callbacks = 0
        self.max_structures = 0
        self.finished = False

    async def on_step(self, iteration):
        assert self.race == Race.NoRace
        self.callbacks += 1
        self.max_structures = max(self.max_structures, self.structures.amount)

    async def on_end(self, result):
        assert result is None
        self.finished = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--replay', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    matches = [GameMatch(
        'MPSC2TeamArena', [Bot(Race.Terran, VerifyBot()) for _ in range(4)],
        team_ids=teams, realtime=realtime, random_seed=17, disable_fog=True, game_time_limit=15,
        output_dir=args.output / str(i), save_replay_as=args.output / str(i) / 'game.SC2Replay',
    ) for i, (teams, realtime) in enumerate((([7, 9, 7, 9], False), ([7, 7, 7, 9], True)))]
    results = run_multiple_games(matches)
    evidence = {'matches': [], 'replays': []}
    for match, result in zip(matches, results):
        assert all(player.ai.ended and player.ai.result == result[player] for player in match.players)
        evidence['matches'].append({'teams': match.team_ids, 'realtime': match.realtime,
                                    'results': [result[player].name for player in match.players]})
    replay_paths = [Path(matches[0].save_replay_as)] + ([args.replay] if args.replay else [])
    for path in replay_paths:
        observer = VerifyObserver()
        result = run_replay(observer, path, step_size=224)
        assert observer.finished and observer.callbacks > 0 and len(result) == 4
        if path == args.replay:
            assert observer.max_structures > 4
        evidence['replays'].append({'path': str(path), 'callbacks': observer.callbacks,
                                    'max_structures': observer.max_structures,
                                    'results': {pid: r.name for pid, r in result.items()}})
    (args.output / 'validation.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps(evidence, indent=2))


if __name__ == '__main__':
    main()
