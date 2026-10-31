from mpsc2.bot_ai import BotAI
from mpsc2.data import Race
from mpsc2.player import Bot

from mpsc2 import maps, run_game


class AttackBot(BotAI):
    async def on_step(self, iteration):
        if self.enemy_units:
            for unit in self.units:
                unit.attack(self.enemy_units.closest_to(unit))


if __name__ == "__main__":
    results = run_game(
        maps.get("MPSC2TeamArena"),
        [Bot(Race.Terran, AttackBot()) for _ in range(4)],
        team_ids=[0, 0, 1, 1],
        realtime=True,
        disable_fog=True,
    )
    print(results)
