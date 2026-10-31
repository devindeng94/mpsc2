"""Sequential self-play episodes; run: python examples/batch_games.py --output reports/batch-new"""
import argparse
from pathlib import Path

from mpsc2 import GameMatch, run_multiple_games
from mpsc2.data import Race
from mpsc2.player import Bot
from minimal_four_player import AttackBot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    # Distinct bot objects, a reproducible seed and a fresh directory per episode.
    args.output.mkdir(parents=True, exist_ok=False)
    matches = [GameMatch(
        'MPSC2TeamArena', [Bot(Race.Terran, AttackBot()) for _ in range(4)],
        team_ids=teams, random_seed=7, disable_fog=True, game_time_limit=30,
        output_dir=args.output / str(i), save_replay_as=args.output / str(i) / 'game.SC2Replay',
    ) for i, teams in enumerate(([0, 0, 1, 1], [0, 0, 0, 1], [0, 1, 2, 3]))]
    for match, results in zip(matches, run_multiple_games(matches)):
        print(match.team_ids, [results[player].name for player in match.players])


if __name__ == '__main__':
    main()
