# MPSC2

Multiplayer self-play for StarCraft II, using familiar python-sc2 APIs.

MPSC2 runs **2–8 independent SC2 processes and API clients** in one match.
Equal `team_ids` cooperate; different IDs compete. Each player controls its own
units. Teammates share vision and native victory/defeat results. Team layouts
include 2v2, 3v1, 4v4 and free-for-all.

Existing bots use **burnysc2 7.3.0**. Keep your `sc2` imports and change the
launcher, or use the equivalent `mpsc2` imports. MPSC2 is a game orchestration
library; training algorithms, rewards and trajectory storage remain your code.

**Alpha: 0.3.1a2.** The bundled multiplayer scenarios currently require
**macOS and the exact supported SC2 5.0.15 / Base96883 executable**. Three or
more clients use a native lobby bridge and a guarded observation fix in runtime
memory. Installed SC2 files are unchanged. Windows/Linux multiplayer backends,
arbitrary multiplayer maps and remote hosts are not implemented.
See [compatibility](docs/compatibility.md) and [known issues](docs/known-issues.md).

## Install

Requirements: **Python 3.10+**, a separate SC2 installation, and Apple's
`clang` command-line compiler for the native multiplayer backend. The tested
Python versions are 3.10 and 3.13; the declared minimum is 3.10.

Clone the repository, then create an environment and install:

```sh
git clone https://github.com/devindeng94/mpsc2.git
cd mpsc2
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
python -m mpsc2 --version
python -m mpsc2 maps
python -m mpsc2 doctor
```

Alternatively, use GitHub's **Code → Download ZIP**, extract it, and run the
environment and installation commands from the extracted directory.

For development, replace `pip install .` with `pip install -e '.[dev,build]'`.
The equivalent requirements-file commands are `pip install -r requirements.txt`
and `pip install -r requirements-dev.txt`, respectively.

The maps and native helper sources are packaged; no map copying is needed.
`doctor` checks multiplayer prerequisites without launching SC2. It exits 1
when any check fails. This repository does not assume a published PyPI package.
See the [installation guide](docs/installation.md) for SC2 setup, custom paths,
Windows/Linux offline development, dependencies and troubleshooting.

## First four-player match

This command launches four independent clients in a 2v2 combat fixture:

```sh
python examples/multiplayer.py --players 4 --teams 0 0 1 1 --output reports/first-game
```

Use a **fresh output directory** for every run. Add `--realtime` for automatic
engine advancement, use `--teams 0 0 0 1` for 3v1, or omit `--teams` for
free-for-all. Set `--players` to any count from 2 through 8.

The equivalent Python API is:

```python
from mpsc2 import run_game
from mpsc2.bot_ai import BotAI
from mpsc2.data import Race
from mpsc2.player import Bot


class AttackBot(BotAI):
    async def on_step(self, iteration):
        if self.enemy_units:
            for unit in self.units:
                unit.attack(self.enemy_units.closest_to(unit))


if __name__ == "__main__":
    results = run_game(
        "MPSC2TeamArena",
        [Bot(Race.Terran, AttackBot()) for _ in range(4)],
        team_ids=[0, 0, 1, 1],
        realtime=False,
        disable_fog=True,
        output_dir="reports/my-game",
        save_replay_as="reports/my-game/game.SC2Replay",
    )
    print(results)  # Native Result values, in input player order.
```

Every player needs its own bot instance. Team IDs can be arbitrary integers;
at least two teams must compete. In notebooks, use `await run_game_async(...)`.

## Choose a scenario

| Scenario | What it provides | Start here |
| --- | --- | --- |
| `MPSC2TeamArena` | Six Marines per player, regardless of selected race; useful for control and team experiments | [Minimal example](examples/minimal_four_player.py) |
| `MPSC2Melee` | Race-specific starting base, 12 workers, 50 minerals, mining, construction, training and research; one expansion site per player | [Full economy example](examples/full_game.py) |
| A standard installed melee map | Normal python-sc2 one/two-player routing, including one BotAI versus the built-in Computer; omit `team_ids` | [Computer opponent example](examples/versus_computer.py) |

The bundled scenarios are research fixtures, not ladder maps. Two bots on these
scenarios use stock two-client hosting within the supported macOS backend;
three through eight use the native bridge. Standard games follow upstream's
platform requirements and do not gain multiplayer support on other platforms.

```sh
python examples/full_game.py --teams 7 9 7 9 --output reports/economy
python -m mpsc2 replay reports/economy/game.SC2Replay
```

See the [examples guide](examples/README.md) for realtime matches, replay
analysis, batch self-play and research checks. For existing bots, start with
the [migration guide](docs/migration.md): multiplayer requires replacing
single-opponent assumptions as well as changing the launcher.

## Validation and limitations

Version 0.3.1a2 fixes the research-related observation crash for native player
IDs ≥4. Live regression tests cover normal-resource research with every count
from **2 through 8**, four-player realtime with zero `Step` requests, and
four/eight-player replay views. **227 offline tests pass on Python 3.10 and
3.13**, both from source and from the installed wheel.

A six-client startup timed out before a successful retry. The eight-player
macro fixture completed every upgrade but missed three expansions. These
failures remain recorded; long training campaigns and every SC2 ability have
not been validated. Read the [research report](docs/research-validation.md),
[player-count report](docs/player-count-validation.md) and
[known issues](docs/known-issues.md) before choosing a workload.

GitHub Actions runs offline tests and packaging checks. It does not install or
run SC2, and configured CI platforms are not evidence of native backend support.

## Documentation and contribution

- [Documentation index](docs/README.md) — installation, API, architecture and troubleshooting.
- [API reference](docs/api.md) — launchers, teams, callbacks, replays and batches.
- [Contributing](CONTRIBUTING.md) — development, map maintenance and validation.
- [GitHub publishing guide](docs/publishing.md) — prepare the first repository and alpha release.
- [Changelog](CHANGELOG.md) — version history.

MPSC2's original code is [MIT licensed](LICENSE). It is an independent research
project, unaffiliated with Blizzard. SC2 itself is installed separately.
Upstream Python and terrain notices are retained in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
