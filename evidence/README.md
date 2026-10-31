# Validation evidence

Public summaries retain dates, versions, native player mappings, measured
outcomes and artifact hashes. Successes and failed attempts are both recorded.

| Record | Scope |
| --- | --- |
| [Four-client prototype](2026-10-28/four-client-success.md) | Original independent-client control, fog and native team results |
| [Prototype artifact hashes](2026-10-28/four-client-success/sha256.json) | Checksums of the preserved local raw evidence |
| [Full economy](2026-10-29/full-economy-validation.json) | Four-player mining, construction, production, expansion and combat |
| [API compatibility](2026-10-30/api-compatibility-validation.json) | Earlier compatibility and packaging checks |
| [Player counts](2026-10-30/player-count-validation.json) | 2–8 players and the built-in Computer route |
| [0.3.1a1 audit](2026-10-30/alpha-release-validation.json) | Broad audit, including the original research failure |
| [0.3.1a2 research fix](2026-10-30/research-fix-validation.json) | Research and replay regression results, including retained failures |

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
