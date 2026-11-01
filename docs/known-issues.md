# Known alpha issues

## MPSC2-001: upgrade observations assumed a single opponent

**Fixed in 0.3.1a2 on macOS Base96883, in 0.3.2a1 on Windows Base93333, and
adapted in 0.3.2a3 for Windows Base98370 and 0.3.2a4 for Base75689.** Each profile requires its exact
validated executable checksum.

The 0.3.1a1 audit reproduced a crash in four-client mixed-race games as soon
as research began. The client with native player ID 4 received an
`EXC_BAD_ACCESS` while constructing an observation. Its research command and
simulation step had already succeeded; Python then reported
`ConnectionAlreadyClosedError`.

Runtime inspection identified the exact cause: SC2's observation serializer
computes a single opponent ID as **`3 - player_id`**. For player 4 this wraps to
`0xffffffff`, which is then used to index an upgrade table. This also affects
selected-player replay views with IDs 4 or higher. Moving Zerg to the host and
changing `raw_affects_selection` could not repair that arithmetic.

The affected code builds an extra private protobuf field (PlayerRaw field 4).
A stock two-player replay confirmed that it contains the opponent's upgrade
IDs. It is separate from the public `PlayerRaw.upgrade_ids` field 3 defined in
[Blizzard's protocol](https://github.com/Blizzard/s2client-proto/blob/master/s2clientprotocol/raw.proto).
There is no single opponent in a general multiplayer game, and the pinned
Python bindings do not expose this extra field.

The macOS fix skips only that private opponent-upgrade block. Every independent
client in a 3–8-player session loads a small native guard. After SC2 unpacks
its code, the guard checks the executable UUID, expected instructions and page
permissions, writes a seven-byte branch on a private in-memory page, and
restores read/execute protection. Python also checks the whole executable's
SHA256 and waits for a successful guard report before connecting to that
client. A failed guard stops startup and releases the owned process.

**This changes runtime executable memory**, unlike the original host lobby
bridge, which changes runtime data only. Installed game files remain untouched.
Own upgrade observations, callbacks, unit statistics, resources, actions and
simulation rules are preserved. The two-client route does not load either
helper. On this build, replay views with IDs >=4 use the same guard; other
views retain the ordinary replay path.

Windows Base93333 refuses code-page protection changes. Its separate guard
validates instruction signatures, then handles only the access violation at
the verified invalid lookup for player IDs 4–8. It checks the faulting address
and registers before resuming after the private block. It changes no SC2 code
bytes. See [Windows validation](windows-validation.md) for live research and
replay results.

Reproduce with a fresh output directory:

```sh
python scripts/validate_alpha.py --phase races --step-size 32 --output reports/research-fixed
python scripts/verify_research_replay.py reports/research-fixed --playback
python scripts/validate_alpha.py --phase races --research-only --realtime --output reports/research-realtime
python scripts/validate_alpha.py --phase races --research-only --step-size 32 --races Terran Protoss Zerg Random Terran Protoss Zerg Random --output reports/research-eight
```

See [research regression validation](research-validation.md) for measured
coverage and the original failed attempts. These checks do not establish every
upgrade, ability, build or platform as supported.

## Startup reliability and broader coverage

Windows Base98370 crashes during offline chat when launched with an explicit
`-dataVersion` on the tested installation. Its profile omits that flag and
verifies installed data before games and replays. It refuses a different loaded
build or data hash; historical data forcing is not supported for this profile.
See [the Base98370 record](windows-98370-validation.md).

The bounded eight-player macro fixture completes research for every player,
but three slots do not complete their attempted expansions before its time
limit. The full macro assertion remains recorded as failed; see the
[research validation](research-validation.md) for the separate research checks.

An earlier eight-client launch and one six-client research-regression launch
timed out at their 90-second join barriers. The six-client attempt had four of
six native readiness events and never reached gameplay. A fresh six-client
retry and later eight-client launches passed, but the initial cause is
unconfirmed. The project has not
established a startup failure rate, long-training reliability, remote-host
support, Linux native multiplayer, or arbitrary-map compatibility.
See [player-count validation](player-count-validation.md) and the
[alpha audit](alpha-validation.md).
