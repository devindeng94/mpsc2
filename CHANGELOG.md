# Changelog

## 0.3.1a2 — multiplayer research fix

- Prepare public-alpha onboarding, requirements entry points, installation and
  troubleshooting guides, GitHub issue/PR templates, and publishing instructions.
- Exclude machine-specific raw evidence from Git uploads while retaining the
  original files locally and publishing compact validation records and hashes.
- Fix MPSC2-001: Base96883's observation serializer computes an opponent ID as
  `3-player_id`, underflowing for player IDs >=4 when upgrade data exists.
- Add an executable-hash/UUID/instruction-guarded process-local observation fix
  to every 3–8-player client, preserving public own-upgrade data and simulation.
  Installed SC2 files remain unchanged; the two-client route remains stock.
- Apply the same fix to affected selected-player replays, with owned cleanup.
- Add research, upgrade-event and replay-effect regression checks, plus startup
  refusal tests. Preserve the original alpha audit failures as historical evidence.

## 0.3.1a1 — alpha release preparation

- Fix selected-player replay failures caused by missing upstream ObserverAI
  damage, type-change and vision callbacks; preserve user overrides and class identity.
- Use verified pytest/Hypothesis development dependencies for Python 3.10.0.

- Release owned SC2 processes even if WebSocket cleanup raises, and return
  automatically allocated standard async-game ports on exit.
- Honor each BotAI's `raw_affects_selection` setting in native joins and record
  its actual protocol value in the API journal.
- Audit every compatibility-module export and run the upstream 7.3.0 offline
  tests through `mpsc2` imports against unchanged SC2 data fixtures.
- Add opt-in live release checks for races, upgrades, queries, callbacks, fog,
  async APIs, cancellation, policy errors, and replay observers.
- Expand offline CI to Linux/macOS/Windows and retain test/coverage artifacts.
- Record the unresolved research-triggered four-client engine crash as
  MPSC2-001; exclude bridged research from advertised alpha support.

## 0.3.0 — unreleased

- Generalize multiplayer launch, native readiness/discovery, ports, MapInfo slots,
  Galaxy triggers, team metadata and result ordering from four players to 2–8.
- Use stock hosting without the native bridge for two independent clients.
- Expand melee starting bases and expansion sites for five to eight players while
  preserving the four-player topology and source-map checksums.
- Retain `NativeFourSession` as a compatibility wrapper and expose
  `NativeMultiplayerSession(players=N)` for lower-level callers.
- Add per-count engine validation, readiness diagnostics, a variable-count example
  and a standard one-BotAI-versus-Computer example.
- Check map resource footprints against the actual playable area and reject
  engine-displaced starting townhalls before invoking policies.
- Validate every count from two through eight in both timing modes, and one
  BotAI versus the built-in Computer; pass 149 tests on Python 3.10 and 3.13.

## 0.2.0 — unreleased

- Re-export core python-sc2 modules under `mpsc2`, preserving type and enum identity.
- Route standard one/two-player games to burnysc2 with its original argument order.
  Add an async standard-game adapter and default four-player free-for-all teams.
- Package combat and full-economy maps and resolve them by name from any directory.
- Add immutable team metadata, visible allied-unit helpers and enemy-race mappings.
- Add `GameMatch` and sequential batch launchers with native result mappings.
- Add replay analysis/viewing APIs and CLI, observed-player selection, bounded
  previews, paced playback and an observer structure-classification fix.
- Add installation diagnostics, migration/API/support documentation, examples,
  CI and distribution metadata. Adopt MIT and retain third-party notices.
- Preserve the checksum-guarded macOS Base96883 four-client backend and its
  stepped/realtime lifecycle, separate ownership and native team results.

## 0.1.0 — research prototype

- Established four independent native SC2 participants through a local host bridge.
- Added combat/economy fixtures, arbitrary team labels, BotAI callbacks, evidence
  reports and replay recording.
- Verified full Terran economy games in stepped and realtime 2v2.
