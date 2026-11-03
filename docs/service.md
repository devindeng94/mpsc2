# Experimental multiplayer service (protocol 1.0)

MPSC2 now includes a local service that separates match orchestration from the
SC2 engine backend. Agents can use existing SC2 gameplay messages or explicit
joint turns. Every agent retains its own SC2 process, native player ID, API
connection and player perspective. The existing `mpsc2.run_game` API continues
to work without starting a service.

This first implementation covers the design's backend, control service and
joint-turn stages. It wraps the validated native adapters. It does **not**
implement automatic binary discovery, a replacement SC2 engine API or support
for Mac Base98310. Those remain separate research work. A protocol can isolate
engine dependencies; it cannot supply missing engine functions.

## Install and run the examples

From a source checkout:

```sh
python -m pip install -e .
python examples/service_joint_turns.py \
  --sc2-path /path/to/StarCraftII \
  --sc2-version 5.0.15.96883 \
  --output reports/service-joint-demo --teams 0 0 1 1
```

Use an installation and version supported on your operating system (see
[version profiles](version-profiles.md)). Paths and versions are explicit; the
service never silently chooses an older installation. On this project's Mac,
the separately prepared Base96883 installation is used explicitly. The example
runs four no-op policies through real WebSocket endpoints until the arena's
native game-time limit. Change teams to `0 1 2 3` for FFA or `0 0 0 1` for 3v1.

For ordinary BotAI mining, construction, production and combat:

```sh
python examples/service_botai.py \
  --sc2-path /path/to/StarCraftII \
  --sc2-version 5.0.15.96883 \
  --output reports/service-botai-demo --teams 0 0 1 1
```

This uses the unchanged `MacroBot` from `examples/full_game.py` and saves a
native replay. Add `--realtime` for the engine's realtime clock. The examples
start an embedded local server; gameplay still crosses its network endpoints.
No `protoc` installation is necessary to use the Python package.

## A persistent local service

Create a private token file and configuration outside version control. The file
must contain a random ASCII token of at least 32 characters; for example:

```sh
python -c "import secrets; from pathlib import Path; p=Path('controller.token'); p.touch(mode=0o600, exist_ok=False); p.write_text(secrets.token_hex(32))"
```

Example `service.json` (paths are relative to this configuration file):

```json
{
  "installations": {
    "research-engine": {
      "root": "/path/to/StarCraftII",
      "version": "5.0.15.96883"
    }
  },
  "maps": {
    "arena": "/path/to/mpsc2/maps/MPSC2TeamArena.SC2Map",
    "melee": "/path/to/mpsc2/maps/MPSC2Melee.SC2Map"
  },
  "output": "reports/service-matches",
  "controller_token_file": "controller.token"
}
```

```sh
python -m mpsc2.service --config service.json --port 5000
```

The service binds only `127.0.0.1`. It requires a controller bearer token and
issues separate, expiring player tokens. Do not publish token files. Changing
the CLI port does not enable remote hosting; encrypted remote access, distributed
engine hosts, match recovery after a daemon crash and observer endpoints are
not implemented.

Protocol IDs use 1–128 ASCII letters, digits, underscores or hyphens.
Only the controller can prepare/start/close matches. Registering installations
and map files is a local operator action, not a remote filesystem API. Prepare
verifies the exact executable and actual Ping identity before CreateGame. It
returns `MATCH_PREPARED`; start joins the native clients, configures the map and
checks the roster/alliances before returning `MATCH_RUNNING`.

## Python client

```python
import asyncio
from contextlib import AsyncExitStack
from pathlib import Path
from mpsc2 import maps
from mpsc2.service import ControlClient, TurnClient, match_spec

async def main():
    spec = match_spec(
        "research-engine", "arena", maps.get("MPSC2TeamArena").path,
        team_ids=[0, 0, 1, 1], joint_turns=True, step_count=8,
    )
    token = Path("controller.token").read_text().strip()
    async with ControlClient("http://127.0.0.1:5000", token) as control:
        prepared = await control.prepare(spec, request_id="my-experiment-001")
        try:
            snapshot = await control.start(prepared)
            async with AsyncExitStack() as stack:
                policies = [await stack.enter_async_context(TurnClient(prepared, p.slot_id))
                            for p in prepared.players]
                # Explicit no-op actions. Pass a RequestAction for real actions.
                for policy in policies:
                    await policy.submit(0, snapshot.game_loop)
                results = await asyncio.gather(*(p.result(0) for p in policies))
                print([r.observation.observation.player_common.player_id for r in results])
                await control.close_match(prepared)
        finally:
            await control.close_match(prepared)

asyncio.run(main())
```

Distribute each player only its own endpoint/token; the controller owns the
complete `PreparedMatch`. The supplied convenience client takes that message
locally. A separate policy worker can use the wire protocol directly with only
its slot credential and `MatchRef`.

For ordinary bots, construct a spec with `joint_turns=False` and call
`await play_botais(control, spec, [Bot(...), ...], save_replay_as=...)`.
This runner invokes the existing BotAI callbacks and uses one `ProfileClient`
per agent. Direct consumers can use `async with sc2_client(prepared, slot)`
after start and call familiar Client methods. They must not call JoinGame:
joining belongs to the control plane. BotAI ability translation happens only
in these policy-side clients; the server forwards native catalog IDs.

## Scheduling and failures

- Joint turns acknowledge immutable buffering immediately. After all agents
  submit, the coordinator dispatches all actions, collects real engine action
  results, advances every client once and verifies their observations. Submit
  every player before waiting for results; no missing action becomes a no-op.
- Native GameOver propagates asynchronously. Every client must report native
  `ended` status and the same complete result table. Terminal frames retain their
  actual values; there is no terminal Step bound or synchronized-frame claim.
  The match omits a common `game_loop` when none exists. All nonterminal rounds
  still require exact common advancement; terminal frames cannot move backwards.
- SC2-compatible actions receive their actual engine acknowledgments immediately.
  Step is a barrier: every agent must request the negotiated count. It has a
  weaker simultaneous-action contract than joint turns. A player cannot submit
  actions after its Step vote for that round.
- Realtime accepts ordinary gameplay requests and rejects Step. Slow observations
  from one player do not hold up another player's actions. Observation loop
  numbers retain their native values; there is no common realtime frame claim.
- Duplicate joint submissions return the existing receipt/result. Conflicting
  submissions or a stale generation fail. State-changing control requests with
  the same request ID/content reuse the original operation and outcome. Use
  the same ID when recovering from a lost Prepare/Start response.
- Timeout, disconnect, invalid ownership, partial action dispatch or unexplained
  clock divergence fail/truncate the match and close its owned engines. There
  is no rollback or blind action retry after uncertain execution. A timeout
  is not a competitive defeat or a native tie.
- Before exposing gameplay, the Linux adapter can recover once from a fully
  stalled JoinGame with no returned player IDs or native start markers. It
  preserves the failed attempt and replaces all owned processes and game ports.
  `StartMatch` returns the authoritative engine-instance and native-player
  bindings; physical instance IDs may differ from `PrepareMatch` after this
  recovery. Slot IDs, teams, credentials and the match generation stay fixed.
  This does not retry policy callbacks or gameplay requests. See
  [Linux startup recovery](linux-startup-recovery.md).
- A player can read only its own native connection. Debug, MapCommand, fog
  disabling and lobby administration are rejected. Scenario setup chat is
  reserved. SaveReplay is supported on the SC2-compatible endpoint, including
  after native game termination. Joint-only replay export is not yet exposed.

The default service allows one allocated match at a time, a one-hour match
lease, 64 retained match records, a 128 MiB serialized turn-history budget per match, 2,048
state-changing control request records, eight outstanding messages per socket
and 32 MiB frames. Limits are explicit; exceeding them fails instead of silently
re-executing evicted mutations. Start a new service after exhausting retained
record limits. Close matches before disconnecting their policies. Abandoned
prepared matches and running matches are closed when their lease expires.

## Backend coverage and extension

The wire format has no four/eight-player ceiling. The initial native factory
accepts the current validated **2–8 independent agent** configurations on the
bundled arena/melee maps: fixed opposing teams, shared allied vision, no shared
unit control, allied victory, raw interfaces, stepped or realtime play. Built-in
Computer/Human slots, arbitrary maps, rendered interfaces and alternative
alliance rules are rejected by this backend. Standard `mpsc2.run_game` support
for Bot-versus-Computer remains available separately.

`NativeFactory.probe` is static evidence, not a gameplay certification. Preparation
adds actual engine identity and `api_ping_verified`; start checks ownership and
map setup. Requested capabilities must also match the chosen timing/transport.
The service supports the existing native OS adapters; live coverage of this
new service must be read separately from historical backend tests.

To add an engine family, implement the `Backend` protocol in
`src/mpsc2/service/backend.py` and a factory with `probe(spec)` / `create(spec,id)`.
The coordinator requires distinct native clients, full roster evidence, real
per-player observations and exactly one all-client advance per round. A backend
must implement owned-resource cleanup even when preparation or joining fails.
The protocol tests use a simulated 12-player backend to verify that the
coordinator is count-independent; this is **not** evidence that SC2 accepts 12.

The schema is in `protocols/mpsc2/v1/multiplayer.proto`; regenerate the small
MPSC2 Python binding with `python tools/generate_service_protocol.py` using a
local `protoc` compiler. Upstream SC2 messages are imported from the installed
package, not copied. See the [design RFC](designs/general-multiplayer-api.md).

Match output retains the actual generated map and its source, native session
metadata, setup checks and a request journal with timestamps, request hashes,
loop numbers and native results. The journal contains no player/controller
tokens. A request hash records identity, not a full replayable action stream;
save a native replay where supported.

## Verification on 2026-11-03

[Recorded evidence](../evidence/2026-11-03/multiplayer-service.json) includes:

- 452 source tests passed, with five existing optional/platform skips.
- Python 3.10 service import and authenticated protocol negotiation passed.
- Real Mac Base96883 joint-turn games with every count from 2 through 8,
  four-player FFA, 3v1 and 2v2, with independent native IDs/processes.
- Four catalog-selected movement actions were accepted by the engine and moved
  each player's own unit through the joint-turn endpoint.
- Four unchanged MacroBots passed the full economy checks, including mining,
  building, production, expansion and combat; the native replay was saved and
  its engine/data version parsed.
- A short four-player realtime BotAI game completed and saved a replay.
- All 83 native process IDs recorded across successful and failed test attempts
  were checked after the runs; none remained as a running SC2 process.

An initial eight-client attempt timed out during native joining and was cleaned
up; fresh attempts later succeeded. The service does not hide this existing
startup reliability limitation or automatically replay failed games. Testing
also refined terminal semantics: SC2 GameOver frames are asynchronous completion
records. The earlier strict terminal-frame checks and idle-controller heartbeat
failure are retained in the evidence alongside the fixes and successful retests.

The subsequent [Linux service validation](../evidence/2026-11-03/linux-multiplayer-service.json)
used the same package on Linux x86_64 SC2 4.10.0/Base75689. The installed wheel
passed 454 tests (three platform skips). All 11 smoke cases passed, including
2–8 joint-turn clients, team layouts, movement and four-player realtime play.
Four MacroBots passed the full economy/combat assertions. A separate
Terran/Protoss/Zerg/Random match passed production, research, expansion and
native replay verification, including selected-player playback for ID 4.
See [Linux commands](linux.md#experimental-service-api) to reproduce the examples.
The existing launcher's Linux regression also covered 2–8 players in both clock
modes and standard games. One seven-player realtime attempt timed out at native
joining; explicit fresh seven/eight-player matches passed. The failed attempt
and existing upstream standard-game teardown warnings remain in the record.
The service's Windows gameplay has not been newly validated in these records.
