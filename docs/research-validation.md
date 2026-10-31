# Multiplayer research regression validation

The 0.3.1a2 fix addresses **MPSC2-001**, the upgrade-related observation crash
found during the [0.3.1a1 release audit](alpha-validation.md). The [known-issue
record](known-issues.md) explains the exact cause and runtime guard.

## Root-cause evidence

- The original and fresh unmodified four-client runs fail when the client with
  native player ID 4 requests an observation after research starts.
- The failing instruction loads an upgrade-table entry with index
  `0xffffffff`. Its caller calculates that index as unsigned `3-player_id`.
- A stock two-client research replay independently identifies the separate
  private opponent-upgrade field: observing Zerg yields own upgrade 66 and
  unknown protobuf field 4 containing opponent upgrade 7 (Terran infantry +1).
  Public `PlayerRaw.upgrade_ids` is field 3, and remains unchanged.
- The corrected code skips only the private opponent-upgrade block. The host
  discovery/readiness bridge, maps, research actions and simulation are unchanged.

The installed executable SHA256 remains
`7a8e076ce304d6cc18591eed03bda5ea68a8639826c0b7364de3f53a3da8e0eb`.
The guard checks Mach-O UUID `DA36F25F-C234-30EB-BE05-E4BC16017B08`, three
instruction signatures and executable-page protections before applying the
process-private branch. It restores read/execute protection and writes a
per-process report before Python permits API connection.

## Regression checks

Every research test uses normal resources and build orders: mining, workers,
production buildings, gas, army units and a completed upgrade. The policy also
attempts an expansion; focused `--research-only` runs record it separately.
There are no debug requests, free upgrades or substituted computer players.
Terran researches infantry weapons +1, Protoss ground weapons +1 and Zerg
Metabolic Boost. Random slots are checked against their actual assigned race.
Native ID order is mapped independently of input order.

Stepped research checks pass for **every player count from 2 through 8**.
The two-client control loads neither native helper. Each test verifies separate
processes and ports, normal-resource production, one own-upgrade callback per
player, native replay upgrade events, native results and owned-process cleanup.
Four- and eight-player replay playback also passes for both the all-player view
and the highest player ID's view, including visible weapon upgrade levels.

| Independent clients | Mode | Completed upgrades | Notes |
| --- | --- | --- | --- |
| 2 | Stepped | 2/2 | Stock route; neither helper loaded |
| 3 | Stepped | 3/3 | Native guard in every client |
| 4 | Stepped | 4/4 | Original full macro fixture, including expansions, passes |
| 5 | Stepped | 5/5 | Native guard in every client |
| 6 | Stepped | 6/6 | Fresh retry; earlier join timeout retained below |
| 7 | Stepped | 7/7 | Native guard in every client |
| 8 | Stepped | 8/8 | Research passes; separate expansion assertion fails below |
| 4 | Realtime | 4/4 | Zero `Step` requests across all four clients |

Every successful game reaches native `Tie` results at the fixture's time limit.
Four- and eight-client stepped fixtures use a step size of 32; the other
stepped checks use 112. The original four-client fixture and realtime check use
`raw_affects_selection=True`; the other counts use `False`.

The four-player original fixture passes its full production/research/expansion
checks. The eight-player game completes all eight upgrades and reaches a native
draw, but its broader macro check fails: two Protoss slots and one Terran slot
do not complete an expansion before the 500-Galaxy-second limit (five of eight
do). That failed macro assertion is retained. Independent research verification
passes for all eight players; this is not a claim that the eight-player macro
policy satisfies every expansion requirement.

One six-client attempt stopped at the 90-second join barrier, with four of six
native readiness events. It never reached gameplay and its owned processes
were released. A fresh retry passed research for all six players. The failed
startup is retained separately; this fix does not claim to resolve startup
reliability.

The exact runs and outcomes are recorded in
[compact evidence](../evidence/2026-10-30/research-fix-validation.json).
Large journals, replays and local diagnostic dumps remain under
`reports/research-investigation/` and are excluded from distributions.

`verify_research_replay.py` decodes native `UpgradeCompleteEvent` records and
matches every player and result against the API report. With `--playback`, it
also checks weapon upgrade effects in the all-player replay view and verifies
own upgrades/callbacks in the highest native player ID's view.

The offline suite includes guard startup ordering/refusal, environment
isolation, compiler failures, stock-route preservation and replay routing.
It passes **227 tests** on Python 3.10 and 3.13, both from source and from the
built wheel outside the checkout with SC2 discovery disabled. Wheel and source
distribution metadata pass `twine check`; all 68 wheel package files match the
source, including both native helpers, and all four license/notice files are
included.
The installed wheel also passes live replay verification on Python 3.10.0 for
the eight-player game, including the all-player view and guarded player-8 view.

## Reproduce

```sh
python -m pip install -e '.[dev]'
SC2PATH=/nonexistent/mpsc2 python -m pytest -q
python scripts/validate_alpha.py --phase races --step-size 32 --output reports/research-four
python scripts/verify_research_replay.py reports/research-four --playback
python scripts/validate_alpha.py --phase races --research-only --realtime --output reports/research-realtime
python scripts/validate_alpha.py --phase races --research-only --races Zerg Terran --output reports/research-two
python scripts/validate_alpha.py --phase races --research-only --step-size 32 --races Terran Protoss Zerg Random Terran Protoss Zerg Random --output reports/research-eight
```

Use fresh output directories. Three-or-more-player games require the guarded
native backend; two-client games remain stock. The same observation bug affects
replays observed from native IDs >=4, so that replay path also requires `clang`
and the exact supported executable.

This fixes a specific observation bug. It does not establish correctness for
every SC2 upgrade, ability, build/platform, remote host or long training run.
The previous alpha's raw failure evidence remains available and is not relabeled
as success.
