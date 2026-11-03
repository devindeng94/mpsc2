# MPSC2 0.3.4a1 — multiplayer service and Linux startup recovery

This alpha adds an experimental multiplayer service with a versioned protocol,
recovers a fully stalled Linux multiplayer startup once, and includes separate
Mac compatibility-engine setup. Python **3.10 or newer** is required. Existing
`mpsc2.run_game`, BotAI, team, realtime and replay APIs remain available.

## Changes

- **Experimental service API:** protocol 1.0, control and per-player WebSocket
  endpoints, explicit engine/map registries, player credentials, asynchronous
  clients, SC2-compatible stepping, joint turns and an opt-in BotAI runner.
  See the [service guide](https://github.com/devindeng94/mpsc2/blob/v0.3.4a1/docs/service.md)
  and [protocol](https://github.com/devindeng94/mpsc2/blob/v0.3.4a1/protocols/mpsc2/v1/multiplayer.proto).
- **Linux startup recovery:** a 3–8-client JoinGame timeout can trigger one clean
  restart with replacement processes and distinct multiplayer ports, only when
  no player has joined and engine logs show no game start or queued join
  response. Failed-attempt logs, startup stages, per-client outcomes and socket
  diagnostics are retained. Partial joins and gameplay are never retried.
  See the [investigation](https://github.com/devindeng94/mpsc2/blob/v0.3.4a1/docs/linux-startup-recovery.md).
- **Mac compatibility setup:** `prepare-macos-compat` prepares a separately
  selected, verified Base96883 engine after the tested Base98310 retail update.
  Early engine exits now report promptly, and probes can check the expected
  build or attach to an existing API endpoint. See
  [installation](https://github.com/devindeng94/mpsc2/blob/v0.3.4a1/docs/installation.md).
- **Release automation:** tagged alpha releases are built and uploaded with
  SHA256 checksums after the Linux/macOS/Windows offline matrix passes.

## Validation

- Final Linux recovery regression: **468 passed, 3 skipped** on Python 3.10.
  Mac regression: **466 passed, 5 skipped** on Python 3.13.
- Linux SC2 4.10/Base75689: ordinary 2-, 4-, 7- and 8-player games completed in
  both stepped and realtime modes. Three naturally stalled starts recovered
  automatically. Controlled recovery also passed through the public service,
  including callbacks, movement and a seven-player replay. All **268 owned
  process identities** checked across the investigation were closed.
  [Recovery evidence](https://github.com/devindeng94/mpsc2/blob/v0.3.4a1/evidence/2026-11-03/linux-join-recovery.json).
- The preceding Linux service audit covers 2–8 clients, team layouts, realtime,
  full economy/combat, mixed-race research and replays.
  [Service evidence](https://github.com/devindeng94/mpsc2/blob/v0.3.4a1/evidence/2026-11-03/linux-multiplayer-service.json).
- Mac compatibility-engine validation covers stepped 2–8-client games,
  four/eight-player realtime economy, eight-player mixed-race research, standard
  games and replay views 0/8.
  [Mac evidence](https://github.com/devindeng94/mpsc2/blob/v0.3.4a1/evidence/2026-11-01/macos-compat-engine.json).

These live checks were performed on development builds before the release
version bump; their dated records preserve exact code identities and failed
attempts. GitHub Actions performs offline tests and packaging checks, not live
SC2 games. Windows profiles and native helper sources are preserved; this
release adds no new live Windows gameplay run.

## Install

Download the attached wheel and, in a Python 3.10+ environment, run:

```sh
python -m pip install --upgrade ./mpsc2-0.3.4a1-py3-none-any.whl
python -m mpsc2 --help
python -m mpsc2 doctor
```

The source archive includes examples, documentation, tests and the protocol
schema. Follow the platform-specific
[installation guide](https://github.com/devindeng94/mpsc2/blob/v0.3.4a1/docs/installation.md)
for SC2 and native compiler requirements. This release is distributed through
GitHub; it does not publish a package to PyPI.

## Limits

The precise native Linux stall trigger remains unconfirmed. Recovery is bounded
to one retry; a second stall still fails. These checks do not establish a
long-training reliability rate.

The service currently runs on one host and still uses explicitly supported
native engine profiles. It does not automatically support new SC2 binaries.
The actual Mac **Base98310 executable remains unsupported**; the separate
compatibility engine uses **5.0.15 rules and data**. The existing upstream
standard-game HTTP-session cleanup warning is retained. See
[known issues](https://github.com/devindeng94/mpsc2/blob/v0.3.4a1/docs/known-issues.md).

No Blizzard executables or game installation data are included in the packages.
