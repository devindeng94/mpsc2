# MPSC2

Multiplayer self-play for StarCraft II, using familiar python-sc2 APIs.

MPSC2 runs **2–8 independent SC2 processes and API clients** in one match.
Equal `team_ids` cooperate; different IDs compete. Each player controls its own
units. Teammates share vision and native victory/defeat results. Team layouts
include 2v2, 3v1, 4v4 and free-for-all.

Existing bots use **burnysc2 7.3.0**. Keep your `sc2` imports and change the
launcher, or use the equivalent `mpsc2` imports. MPSC2 is a game orchestration
library; training algorithms, rewards and trajectory storage remain your code.

**Alpha: 0.3.3a1.** Native multiplayer support is specific to the operating
system, executable architecture and exact SC2 build. Installed SC2 files are
unchanged.

## Supported operating systems and StarCraft II versions

| Operating system | SC2 version / build | Native MPSC2 scenarios (2–8 clients) | Validation and limitations |
| --- | --- | --- | --- |
| Windows, x86_64 | **5.0.15 / Base98370** | **Supported alpha profile** | Live 2–8-player games, research and replays; build-specific native guard, ability IDs and installed-data selection; see [validation](docs/windows-three-build-validation.md) |
| Windows, x86_64 | **5.0.14 / Base93333** | **Supported alpha profile** | Live player-count, stepped/realtime, research and replay checks; tested on Windows 10 x64 |
| Windows, x86_64 | **4.10.0 / Base75689** | **Supported alpha profile** | Separate native layout, legacy ability table and replay startup settings; see the [three-build validation](docs/windows-three-build-validation.md) |
| macOS, x86_64 SC2 executable | **5.0.15 / Base96883** | **Supported alpha profile** | Both Mac helpers preserved byte-for-byte; four-player realtime regression passed during the Linux port; earlier full-game evidence retained |
| Windows | Base92440 | **Unverified; no native profile** | Only an empty directory was present on the test machine; no executable could be tested |
| Linux, x86_64 | **4.10.0 / Base75689** | **Supported alpha profile** | Headless independent clients; GCC required for 3–8 players and replay views ≥4; see [Linux setup](docs/linux.md) |
| Any OS | Other builds or executable hashes | **Unsupported for native multiplayer** | A known version label or an installed folder does not establish compatibility |

The native profiles verify the **exact executable SHA256**, not just its version
label. The macOS profile targets the x86_64 game executable, including an
appropriate Rosetta installation. Three or more clients use a platform-specific
local lobby bridge and observation guard. Arbitrary multiplayer maps and remote
hosts are not implemented.

Inspect the registry and check the local installation:

```sh
python -m mpsc2 versions
python -m mpsc2 doctor --sc2-version 4.10    # Windows / Linux Base75689
python -m mpsc2 doctor --sc2-version 5.0.14  # Windows Base93333
python -m mpsc2 doctor --sc2-version 5.0.15  # Windows Base98370 / macOS Base96883
```

Use `sc2_version="5.0.15"` for the updated Windows build or the existing Mac
build; the alias resolves by OS. Exact selectors such as `"Base98370"` also
work. Omitting the argument preserves the previous defaults: Windows Base93333
and macOS Base96883; Linux defaults to Base75689. Unsupported requests are rejected before
launch and never fall back to another build. SC2 data-version identifiers and
executable SHA256 values serve different purposes; the
[version/profile guide](docs/version-profiles.md) explains the registries and how
to add verified support. See also [Linux setup](docs/linux.md), [Windows setup](docs/windows.md),
[older-build results](docs/windows-older-build-validation.md),
[compatibility](docs/compatibility.md) and [known issues](docs/known-issues.md).

Windows Base98370 uses the installed game data and verifies its build and data
identifier through the API before play. Explicit `-dataVersion` causes an
offline chat crash in this build. If a later SC2 update changes its installed
data, MPSC2 refuses a mismatch instead of silently loading different content.

Windows also accepts exact selectors `"Base75689"`, `"Base93333"` and
`"Base98370"`. Each selects that executable with no fallback. Every Windows
client checks the live ability metadata before play; older engines keep their
required startup hashes. A launch hash or replay data label alone does not
prove historical balance data. See the [three-build guide](docs/windows-three-build-validation.md).

## Install

Requirements: **Python 3.10+**, a separate SC2 installation, and Apple's
`clang` on macOS, **x86_64 Windows Python and MinGW-w64 GCC** on Windows, or **x86_64 Linux Python and GCC** on Linux for 3–8 clients. The tested
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
`doctor` detects the local SC2 installation and checks multiplayer prerequisites
without launching SC2. Use `doctor --mode standard` to check the upstream
one/two-player route on Windows/Linux. Its exit code follows the selected mode;
a Windows multiplayer installation must match its own pinned executable and compiler checks.
This repository does not assume a published PyPI package.
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
For Windows Base98370, add `--sc2-version 5.0.15` to this command (or
`sc2_version="5.0.15"` to the Python call below).

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
scenarios use stock two-client hosting on each supported native platform;
three through eight use that platform's bridge. Standard games follow upstream's
platform requirements.

```sh
python examples/full_game.py --teams 7 9 7 9 --output reports/economy
python -m mpsc2 replay reports/economy/game.SC2Replay
```

See the [examples guide](examples/README.md) for realtime matches, replay
analysis, batch self-play and research checks. For existing bots, start with
the [migration guide](docs/migration.md): multiplayer requires replacing
single-opponent assumptions as well as changing the launcher.

## Validation and limitations

Version **0.3.3a1** passed **361 tests against both source and the installed wheel**
on Linux, plus live stepped and realtime games with every count from **2 through
8**, team layouts, economy, research and replay analysis. The macOS regression
passed **359 tests** and a live four-player realtime match. See
[Linux setup and validation](docs/linux.md) and the
[release notes](docs/release-notes-0.3.3a1.md) for coverage and limitations.

Version **0.3.2a4** passed **334 tests against both source and the installed
wheel** on Windows. **Base75689, Base93333 and Base98370** each passed stepped
games with every player count from **2 through 8**, eight-player mixed-race
normal-resource research, and replay views **0 and 8**. Each also passed
**four- and eight-player realtime** checks, plus a separate four-player
realtime game from the installed wheel. See the
[three-build validation](docs/windows-three-build-validation.md) for exact
coverage, executable identities, ability layouts and retained failed attempts.
Boot hashes and replay labels do not by themselves prove historical balance
data; the actual ability metadata is checked separately for each client.

The preceding **0.3.2a3** passed 321 source/wheel tests and introduced
Base98370's native guard, installed-data launch mode and seven ability-ID
translations. Its [dated report](docs/windows-98370-validation.md) retains
the initial startup/research failures and earlier measurements.

The preceding version **0.3.2a2** passed **299 tests against both source and the installed wheel**
on Windows. Explicit profile selection passed live stepped matches with 2, 4
and 8 independent clients, an installed-wheel four-player realtime match,
four-player research, and replay views 0 and 4. See the
[version-registry validation record](evidence/2026-10-31/version-registry-validation.json).
The [Windows backend record](evidence/2026-10-31/windows-validation.json) covers
every player count from 2 through 8. The macOS helper sources remain unchanged;
macOS was not live-tested again on this Windows host.

The earlier macOS release 0.3.1a2 fixes the research-related observation crash for native player
IDs ≥4. Live regression tests cover normal-resource research with every count
from **2 through 8**, four-player realtime with zero `Step` requests, and
four/eight-player replay views. The offline test and packaging matrix covers
Python **3.10–3.13**, including Windows, macOS and Linux jobs, with installed-wheel
checks outside the source checkout.

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
