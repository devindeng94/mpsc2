# Changelog

## 0.3.2a4 — three Windows engine profiles

- Add a checksum-pinned Base75689 native backend using verified lobby,
  readiness and observation addresses with the existing guarded strategy.
- Inspect each Windows client's live ability metadata before gameplay and
  select legacy 4.10, canonical or shifted-ID translation independently.
- Translate legacy rock-tower IDs, reject conflicting outgoing constants,
  and retain upstream enum identities and macOS behavior.
- Select the exact Windows executable and required boot hash for every replay
  view, including observer zero; load the observation guard only where needed.
- Verify each running engine's build, record its API-reported data identity
  and detected ability layout, and document the separate replay-label limits.
- Validate every stepped count from 2–8, realtime counts 4/8 and eight-player
  research/replay playback on all three Windows builds; preserve Mac helpers.

## 0.3.2a3 — Windows SC2 5.0.15 / Base98370

- Add the verified Base98370 executable, data identifier and native layout.
- Handle the new observation serializer's saved player ID and register layout
  without changing the Base93333 or macOS guards.
- Avoid Base98370's offline-chat crash with installed-data selection; verify
  the build/data identity before games and replay playback and reject mismatches.
- Translate seven relocated ability IDs at this profile's client boundary,
  including worker gas-gather orders; retain existing python-sc2 constants and
  translate outgoing commands back to the engine IDs. Validate ability metadata.
- Resolve `5.0.15` by OS: Base98370 on Windows, Base96883 on macOS. Keep the
  existing omitted-argument defaults and require explicit selection on Windows.
- Extend native guard and data-selection regression tests and document the
  new build's live validation and limits.

## 0.3.2a2 — version and native compatibility registries

- Separate game/data-version metadata from verified OS/architecture/build
  profiles and executable checksums; retain the upstream `VERSIONS` export.
- Select native profiles through `sc2_version`, diagnostics and replay metadata;
  unknown selections fail without falling back to a different build.
- Generate Windows helper constants from the selected profile and verify its ID
  in helper reports. Bind unchanged Mac helpers by source and executable hashes.
- Add `mpsc2 versions`, profile-aware `doctor`, and per-session profile evidence.
- Distinguish empty build directories from installed executables. Record
  Base75689 standard-only measurements and Base92440's missing executable.
- Preserve the existing native defaults and standard-game delegation.

## 0.3.2a1 — Windows native multiplayer

- Add an isolated, checksum-pinned Windows Base93333 backend for 2–8 clients.
- Launch with Support64, build an x64 DLL using MinGW-w64, and forward local
  discovery using packaged BSD-licensed MinHook sources.
- Handle Windows boolean readiness counters with two unused hold slots;
  retain macOS helper sources, pinning, and observation-guard behavior.
- Guard the verified Windows private upgrade-index fault for player IDs 4–8
  in games and selected-player replays, preserving public own upgrades.
- Replace POSIX process-existence probes in live validation with portable
  process identity checks; record Windows process creation times.
- Add Windows launch/refusal/cleanup tests, diagnostics, and setup instructions.
- Read source fixtures as UTF-8 on Windows installations with a non-UTF-8 locale.

## 0.3.1a3 — platform-aware installation diagnostics

- Detect Windows `SC2_x64.exe`, macOS app executables and Linux `SC2_x64`, using
  SC2PATH, ExecuteInfo.txt and upstream platform defaults in that order.
- Report the latest installed build, executable hash, Support64 prerequisite
  and actionable missing-installation errors without launching the game.
- Separate standard-game readiness from native multiplayer readiness. Add
  `doctor --mode standard` and `--output` JSON reports that preserve prior files.
- Refuse native multiplayer on unsupported hosts before resolving macOS paths
  or compiling helpers. Keep the exact macOS executable guard unchanged.
- Resolve the engine probe's default map from the installed package, preserve
  engine/build diagnostics and explicitly distinguish CreateGame acceptance
  from joined clients or working gameplay.
- Probe the stock two-client baseline with exactly two total participants,
  avoiding the old two-client-plus-two-Computers setup that also violated 1v1.
- Add Windows testing instructions. This release does not implement a Windows
  native bridge or claim live Windows multiplayer validation.

## 0.3.1a2 — multiplayer research fix

- Keep the macOS observation-guard path fixture in POSIX form on Windows CI.
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
