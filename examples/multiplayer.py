"""Start 2..8 independent bots; for example, --players 8 --teams 0 0 0 0 1 1 1 1."""
import argparse
from pathlib import Path

from mpsc2 import run_game
from mpsc2.bot_ai import BotAI
from mpsc2.data import Race
from mpsc2.player import Bot


class AttackBot(BotAI):
    async def on_step(self, iteration):
        if self.enemy_units:
            for unit in self.units:
                unit.attack(self.enemy_units.closest_to(unit))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--players', type=int, choices=range(2, 9), default=8)
    parser.add_argument('--teams', nargs='+', type=int, help='One integer per player; omit for free-for-all')
    parser.add_argument('--realtime', action='store_true')
    parser.add_argument('--output', type=Path, help='Fresh output directory, optionally with a replay')
    args = parser.parse_args()
    results = run_game(
        'MPSC2TeamArena', [Bot(Race.Terran, AttackBot()) for _ in range(args.players)],
        team_ids=args.teams, realtime=args.realtime, disable_fog=True,
        output_dir=args.output,
        save_replay_as=args.output/'game.SC2Replay' if args.output else None,
    )
    print([result.name for result in results])
