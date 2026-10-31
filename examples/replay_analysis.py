"""Inspect a replay with ObserverAI: python examples/replay_analysis.py path.SC2Replay"""
import argparse

from mpsc2 import run_replay
from mpsc2.observer_ai import ObserverAI


class InspectReplay(ObserverAI):
    async def on_start(self):
        self.maximum_visible_units = 0

    async def on_step(self, iteration):
        self.maximum_visible_units = max(self.maximum_visible_units, self.all_units.amount)

    async def on_end(self, result):
        # result is None for observed_id=0 (there is no native player zero).
        print('Maximum visible units:', self.maximum_visible_units, 'Selected result:', result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path')
    parser.add_argument('--observed-id', type=int, default=0)
    args = parser.parse_args()
    results = run_replay(InspectReplay(), args.path, observed_id=args.observed_id, step_size=224)
    print({player_id: result.name for player_id, result in results.items()})
