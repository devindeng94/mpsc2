# Linux JoinGame timeout investigation

The Linux adapter now recovers once from a fully stalled 3–8-player JoinGame
before returning clients or running policies. This is a bounded startup
mitigation. The precise native trigger remains unconfirmed.

## What the evidence establishes

The original seven-player realtime match in the
[Linux service audit](../evidence/2026-11-03/linux-multiplayer-service.json)
launched seven independent SC2 Base75689 processes and passed their API Ping
and helper checks. All seven received JoinGame requests. None returned a player
ID or logged `Game has started.` before the 90-second barrier expired.
Native lobby packets continued to flow while Python waited. The final client's
log showed traffic from the host, but no received traffic from the other guests.
This localizes the failure to native lobby/peer establishment, before BotAI
initialization, actions, simulation stepping or the new service protocol.

The follow-up ran twelve repetitions of the original seven-player realtime
settings, eight API-join timing variants (delays from zero to ten seconds), and
one five-second pause at a guest's native TCP connection to the host. All passed.
Captured bind/connect results in these successful runs showed no unexpected
socket errors. These checks do not identify the trigger or prove a failure rate.

A later, ordinary seven-player **stepped** regression hit an unforced 90-second
JoinGame stall with zero returned player IDs. The new recovery path retained
that attempt and completed the replacement game, including actions and replay
checks. Its configured game/API ports did not overlap the concurrently running
service tests. Normal seven- and eight-player realtime checks also needed and
completed their automatic second attempt. The issue therefore is not limited
to realtime mode; a simple
port collision between those test matches does not explain this recurrence.
Timing-sensitive native peer establishment is a working hypothesis, not a
confirmed instruction-level cause.

## Recovery behavior

The existing native session already closed its owned WebSockets and processes
on a barrier timeout. It previously propagated a generic timeout immediately.
The revised Linux adapter:

1. Records the failing startup stage, each input client's join timing/outcome,
   and a passive snapshot of the owned processes' loopback sockets before exit.
2. Closes all owned children and releases their ports. It inspects the closed
   engine logs for native start or queued JoinGame-response markers.
3. Allows one replacement attempt only when every client lacks a successful
   join and every engine log is available and lacks those markers.
4. Moves the complete failed attempt to `session/failed-join-attempt-1/`, then
   allocates distinct multiplayer ports and launches fresh independent engines.
5. Records both attempts in `session/native-session.json`. The second timeout
   remains an error; there is no unbounded retry loop.

Partial joins, native start markers, missing logs, cancellation, configuration
errors and failures during later game-data requests are not retried. Two-player
stock sessions retain one attempt. Policies and gameplay actions are never
replayed. The configured timeout applies to each attempt, so recovery can extend
startup time. Source/executable checksum checks and native helpers are unchanged;
installed SC2 files and the existing installed Python package were preserved.

The service reruns identity checks and applies each player's interface options
to replacement clients. Its StartMatch response contains the final physical
engine bindings and native player IDs. Logical slots, teams, credentials and the
match generation remain unchanged. Consumers should use those final bindings.

## Validation

The [dated evidence](../evidence/2026-11-03/linux-join-recovery.json) retains the
original failure reference, all follow-up attempts and local artifact hashes.
A controlled 60-second pause in one guest's native host connection exceeded a
30-second JoinGame deadline: the pre-change 0.3.3a2 test wheel failed; the revised code
closed the first seven processes and joined seven replacements. This injection
tests recovery from a stalled lobby; it does **not** reproduce or explain the
precise trigger of the original intermittent failure.

The same controlled test through the public service completed a seven-player
realtime game with real movement, exactly one start/end callback per bot, fresh
engine bindings and seven players in its saved replay. Ordinary launch checks
cover 2, 4, 7 and 8 players in stepped and realtime modes, plus an eight-player
service game. Unit regressions check bounded exhaustion, cancellation, partial
joins, native markers, data-request failures, fresh port selection and passive
diagnostic ownership. All eight normal match checks completed; three required
automatic recovery (seven-player stepped, seven- and eight-player realtime).
The final suites passed 468 tests on Linux (three skips) and 466 on macOS (five
skips). All 268 recorded native process identities were closed. These are
bounded tests, not a long-training guarantee.

Run checks from the repository root with a fresh output directory:

```sh
python -m pytest tests/test_linux_session.py -q
python scripts/validate_player_counts.py --counts 2 4 7 8 \
  --sc2-version 4.10.0 --output reports/linux-join-stepped
python scripts/validate_player_counts.py --counts 2 4 7 8 --realtime \
  --sc2-version 4.10.0 --output reports/linux-join-realtime
```

For a new failure, retain `native-session.json`, any `failed-join-attempt-1/`
archive and every `client-*/engine.log`. `join_network` distinguishes missing
listeners or pending TCP connections from established sockets whose native
handshake failed to finish. Socket-snapshot errors are recorded and do
not block process cleanup.
