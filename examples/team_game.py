"""Run 2..8 BotAI policies through independent native SC2 clients."""
import argparse
from pathlib import Path

from sc2.bot_ai import BotAI
from sc2.data import Race
from sc2.player import Bot
from sc2.position import Point2

from mpsc2 import maps, run_game


class MarineBot(BotAI):
    async def on_start(self):
        print(f"Bot {self.player_index}: native player {self.player_id}, "
              f"team {self.team_id}, allies {self.ally_player_ids}")

    async def on_step(self, iteration):
        for unit in self.units:
            # python-sc2 classifies native allies separately from enemies.
            target = self.enemy_units.closest_to(unit) if self.enemy_units else Point2((64, 57))
            unit.attack(target)

    async def on_end(self, result):
        print(f"Bot {self.player_index}: {result.name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--teams", nargs="+", type=int, default=[0, 0, 1, 1])
    parser.add_argument("--output", type=Path, required=True, help="Fresh output directory")
    parser.add_argument("--fog", action="store_true")
    parser.add_argument("--realtime", action="store_true", help="Let SC2 advance automatically")
    args = parser.parse_args()
    print(run_game(
        maps.get('MPSC2TeamArena'),
        [Bot(Race.Terran, MarineBot(), name=f"MarineBot-{i+1}") for i in range(len(args.teams))],
        team_ids=args.teams, realtime=args.realtime, disable_fog=not args.fog, random_seed=7,
        output_dir=args.output, save_replay_as=args.output / "game.SC2Replay",
    ))
