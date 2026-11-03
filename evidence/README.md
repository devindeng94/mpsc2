# Validation evidence

Public summaries retain dates, versions, native player mappings, measured
outcomes and artifact hashes. Successes and failed attempts are both recorded.

| Record | Scope |
| --- | --- |
| [Linux protocol 1.0 service](2026-11-03/linux-multiplayer-service.json) | Installed-wheel tests, real 2–8-client service games, full economy/research/replays and existing-launcher regression on Base75689 |
| [macOS Base98310 retest](2026-11-02/macos-98310-retest.json) | Direct launch, isolated historical metadata, binary comparison, working-engine control, and exact-build/Ping-only diagnostic tests; Base98310 still unsupported |
| [0.3.3a2 Mac compatibility engine](2026-11-01/macos-compat-engine.json) | Separately restored Base96883 app and matching data selection after the Base98310 retail update |
| [macOS Base98310 startup](2026-11-01/macos-98310-startup.json) | Failed stock API startup on the updated Mac; no multiplayer/gameplay claim |
| [0.3.3a1 Linux support](2026-11-01/linux-validation.json) | Linux Base75689, headless 2–8 clients, economy/research and replay analysis |
| [0.3.2a4 Windows three-build support](2026-11-01/windows-three-build-validation.json) | Base75689/Base93333/Base98370 native profiles, live ability tables, exact-engine gameplay and replay verification |
| [0.3.2a3 Windows Base98370](2026-11-01/windows-98370-validation.json) | New build/data profile, ability-ID translation, 2–8 clients, research/replays, realtime, source/wheel checks, and retained limitations |
| [Four-client prototype](2026-10-28/four-client-success.md) | Original independent-client control, fog and native team results |
| [Prototype artifact hashes](2026-10-28/four-client-success/sha256.json) | Checksums of the preserved local raw evidence |
| [Full economy](2026-10-29/full-economy-validation.json) | Four-player mining, construction, production, expansion and combat |
| [API compatibility](2026-10-30/api-compatibility-validation.json) | Earlier compatibility and packaging checks |
| [Player counts](2026-10-30/player-count-validation.json) | 2–8 players and the built-in Computer route |
| [0.3.1a1 audit](2026-10-30/alpha-release-validation.json) | Broad audit, including the original research failure |
| [0.3.1a2 research fix](2026-10-30/research-fix-validation.json) | Research and replay regression results, including retained failures |
| [0.3.2a1 Windows backend](2026-10-31/windows-validation.json) | Windows 2–8 clients, research, replays, packaging, and macOS source preservation |
| [Older Windows builds](2026-10-31/windows-older-build-validation.json) | Base75689 API/gameplay checks and native incompatibility; missing Base92440 executable |
| [0.3.2a2 version registry](2026-10-31/version-registry-validation.json) | Source/wheel tests, explicit profile selection, live 2/4/8 clients, research/replays, and unchanged Mac helpers |

Paths under `reports/` in these records identify **local artifacts**, not files
available in a GitHub checkout. The original raw prototype directory is also
excluded from Git because it includes machine-specific launch paths and binary
protocol captures. Its files remain unchanged locally; the public hash manifest
preserves their identities. Replays, native memory dumps and game installations
are not part of the public source archive.

Build hashes in dated records identify the artifacts tested on that date.
Documentation and packaging changes can produce new hashes without rewriting
historical validation results. Follow the current guides to reproduce checks in
fresh output directories.

- [2026-11-03 multiplayer service](2026-11-03/multiplayer-service.json): protocol conformance, real 2–8-client games, team layouts, movement, full BotAI economy/combat, realtime and preserved failures.
- [2026-11-03 Linux startup recovery](2026-11-03/linux-join-recovery.json): seven-player timeout investigation, three unforced stalls recovered, controlled native/service recovery, passive socket diagnostics, regression suites and cleanup of all 268 owned process identities.
