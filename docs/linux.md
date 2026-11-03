# Linux native multiplayer

MPSC2 0.3.3a1 adds a separate backend for **Linux x86_64 SC2 4.10.0,
Base75689**. Each BotAI has its own headless SC2 process, WebSocket, player ID,
observations and actions. Team IDs support FFA, uneven teams and cooperative
groups competing against each other. All clients run on the same Linux host.

## Install

Requirements: x86_64 Linux, 64-bit Python 3.10+, GCC, and an existing complete
SC2 Linux 4.10 installation. The tested host uses Ubuntu 22.04.5, Python 3.10.12
and GCC 11.4. No display server is required for the native headless route.
SC2 itself is installed separately and is not redistributed with MPSC2.

Linux SC2 resolves standard multiplayer maps under lowercase `maps/`. Some
installations also have an uppercase `Maps/` directory. If a guest reports
`MapDoesNotExist`, check that the selected map is available under lowercase
`maps/`, using a link to the corresponding existing map directory if necessary.
Keep any existing `maps/` content (for example SMAC maps). `doctor` warns about
entries found only under `Maps/`; it does not change the installation.

```sh
git clone https://github.com/devindeng94/mpsc2.git
cd mpsc2
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
export SC2PATH="/path/to/StarCraftII"
python -m mpsc2 doctor --sc2-version 4.10
```

`SC2PATH` is the directory containing `Versions`, game data and `Maps`.
The required executable is `Versions/Base75689/SC2_x64`, with SHA256:

```text
115f65a49191c504f6336f7d5b7818b23dbba3d7a45cacf9142c86c959abaa41
```

Install your distribution's GCC package if it is missing, or set
`MPSC2_LINUX_CC=/path/to/gcc`. The compiler is used for 3–8-client games and
selected-player replay views with IDs ≥4. The two-client route uses stock
hosting without loading a helper. `doctor` checks static prerequisites;
the match below tests actual gameplay.

## Run four players

```sh
python examples/multiplayer.py --players 4 --teams 0 0 1 1 --output reports/linux-2v2
```

Add `--realtime` for automatic engine progression. Use `--teams 0 1 2 3`
for FFA or `--teams 0 0 0 1` for 3v1, with a fresh output directory each time.
Change `--players` and provide one team ID per player for other counts from
2 through 8. At least two distinct teams are required.

The same public API works on Linux:

```python
from mpsc2 import run_game
from mpsc2.bot_ai import BotAI
from mpsc2.data import Race
from mpsc2.player import Bot

class GatherBot(BotAI):
    async def on_step(self, iteration):
        if iteration % 4 == 0:
            await self.distribute_workers()

results = run_game(
    "MPSC2Melee",
    [Bot(Race.Terran, GatherBot()) for _ in range(4)],
    team_ids=[0, 0, 1, 1],
    realtime=True,
    sc2_version="4.10",  # Also the Linux default.
    game_time_limit=60,
    output_dir="reports/linux-economy",
    save_replay_as="reports/linux-economy/game.SC2Replay",
)
print(results)
```

## Replays and validation

Linux replay analysis is headless. `run_replay` and `run_replay_async` support
ObserverAI callbacks; the CLI can advance the replay and report its results:

Replay data is sent directly through the SC2 protocol, so files can stay in
their output directories instead of being copied into a global replay folder.

```sh
python -m mpsc2 replay reports/linux-2v2/game.SC2Replay --fast --observed-id 4
python -m pip install -e '.[dev]'
python -m pytest -q
python scripts/validate_player_counts.py --output reports/linux-counts
python scripts/validate_player_counts.py --realtime --output reports/linux-counts-rt
python scripts/validate_alpha.py --phase races --step-size 32 --output reports/linux-macro
python scripts/verify_research_replay.py reports/linux-macro --playback
```

See the [validation record](../evidence/2026-11-01/linux-validation.json) for
measured coverage. Passing one build does not establish compatibility with
other Linux executables. RGB rendering, distributed hosts, arbitrary multiplayer
maps and more than eight API players are outside this alpha's supported scope.
Ordinary one/two-player maps still use the upstream burnysc2 route.

## Experimental service API

The optional [protocol 1.0 service](service.md) also runs on this Linux profile.
Select the installation explicitly; the service does not need a different SC2
engine or an update to the existing Linux native helper:

```sh
python examples/service_joint_turns.py \
  --sc2-path "$SC2PATH" --sc2-version 4.10.0 \
  --teams 0 0 1 1 --move --output reports/linux-service-joint

python examples/service_botai.py \
  --sc2-path "$SC2PATH" --sc2-version 4.10.0 \
  --teams 0 0 1 1 --game-time-limit 600 --output reports/linux-service-macro
```

Add `--realtime` to the BotAI example for automatic progression. The service
uses loopback endpoints on the Linux host; this does not enable distributed
engine hosts. It forwards native ability IDs, while its BotAI client applies
the existing SC2 4.10 catalog translation.

Run the service smoke matrix with a fresh output directory:

```sh
python scripts/validate_service.py \
  --sc2-path "$SC2PATH" --sc2-version 4.10.0 \
  --output reports/linux-service-matrix
```

The [2026-11-03 service validation](../evidence/2026-11-03/linux-multiplayer-service.json)
records 454 installed-wheel tests passed (three platform skips), all 11 service
smoke cases, full four-player economy/combat, and Terran/Protoss/Zerg/Random
production, research, expansion and replay playback. The smoke cases cover
2–8 joint-turn clients, four-player FFA/3v1/2v2, actual movement and a short
four-player realtime game. Matches are bounded; these results do not establish
long-running training reliability or other Linux builds as supported.

The same audit checked the existing launcher with 2–8 players in stepped and
realtime modes, Bot-versus-Computer and two-agent standard games, mixed-race
research/replay playback, policy exceptions and cancellation. One seven-player
realtime attempt timed out at native JoinGame after 90 seconds. Fresh seven-
and eight-player matches passed, as did a seven-player comparison with the
retained 0.3.3a1 package. The initial failure remains in the evidence; its cause
is unconfirmed. Standard-game teardown also retained the existing upstream
connection/session-close warnings despite passing gameplay and port-release
checks.

No new runtime code change was needed for these tests. The installed SC2
executable checksum and the previous package were preserved. All 151 recorded
native process identities were checked after the runs, with none left alive;
no processes using the selected SC2 executable remained.

## Implementation boundaries

### JoinGame timeout recovery

The follow-up [startup investigation](linux-startup-recovery.md) adds bounded
recovery for a fully stalled 3–8-client Linux lobby. This applies to both the
existing launcher and the service. If JoinGame times out without any returned
player ID or logged native start/JoinGame response, MPSC2 closes the owned
processes and sockets, archives their evidence under
`session/failed-join-attempt-1/`, and tries once with new processes and distinct
multiplayer ports. The timeout applies to each attempt, so recovery can extend
startup time. There are no retries after clients reach the caller or policies
start running. Two-player stock sessions retain one attempt.

`session/native-session.json` records the startup stage, `join_progress` for
each input slot, `join_network` snapshots of owned loopback sockets on timeout,
and `startup_attempts` with paths to earlier evidence. A final
`LinuxJoinTimeout` remains a `TimeoutError` and names the failed stage and
number of completed joins. Missing logs, a partial join, native start markers,
cancellation, configuration errors and later request failures do not trigger
recovery. This is a reliability mitigation, not proof that the underlying
engine race has been eliminated.

Python verifies the full executable hash and binds the helper source by hash.
The helper verifies the ELF build ID, loopback launch arguments, instruction
signatures and private code-page protections before making startup changes.
It changes three host count immediates so normal CreateGame and native readiness
accept the requested count, and forwards local discovery packets to each guest.
It skips only the private single-opponent upgrade field; the public own-upgrade
field and simulation rules remain intact. Each guest receives a distinct port
pair. Linux clients inspect the live legacy ability table before policies run.

The helper is loaded only into the session's child processes. Installed SC2
files and parent environment variables are unchanged. Failure and cancellation
release the session's own processes and ports.
