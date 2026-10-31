# Alpha release validation

Historical **0.3.1a1** audit. Its research failure is fixed in **0.3.1a2**;
see [research regression validation](research-validation.md). The original
measurements and failed attempts below are retained unchanged.

This audit prepares **0.3.1a1** for public alpha testing. It compares MPSC2 with
the pinned **burnysc2 7.3.0** API and tests MPSC2's launch, team, lifecycle,
failure-handling, replay and packaging code. A passing alpha audit is not a
claim that every SC2 unit, ability, platform or training workload has been tested.

**The audit is not fully green.** It found a reproducible four-client engine
crash when upgrade research starts. This alpha must explicitly exclude bridged
multiplayer research; see [MPSC2-001](known-issues.md). Passing results below do
not override that limitation.

## Upstream reference and offline tests

The reference is python-sc2's
[7.3.0 release commit](https://github.com/BurnySc2/python-sc2/tree/0875b4bb953c96a3eea3cc12d1a57b9e208bd95f).
Every Python source file in that checkout was compared byte-for-byte with the
installed dependency before executing its tests.

**232 upstream tests pass on Python 3.10 and 3.13**, using **104 original game-data fixtures**. The
test assertions and fixtures are unchanged; only `from sc2.X` imports are
replaced with `from mpsc2.X`. These cover BotAI state and helpers, Units/Unit,
positions and geometry, ramps and expansion detection, pixel maps, costs and
game data, observations, score, ID tables and expiring dictionaries. The
upstream live cheat/debug-based test bots are not included in this count.

The MPSC2 suite has **214 passing tests** on Python 3.10 and 3.13. It additionally
checks every public symbol in the compatibility shims for upstream identity,
multiplayer map generation for all counts, routing, teams and alliances,
callbacks, native results, realtime cadence, replay previews, errors, cleanup,
CLI behavior and input validation. Offline checks use an invalid `SC2PATH` to
ensure that they do not depend on a game installation.

## Live checks

The live audit runs on macOS with the checksum-pinned SC2 Base96883 executable.
Large logs and replays are stored locally under `reports/alpha-release-audit/`.
The [compact evidence file](../evidence/2026-10-30/alpha-release-validation.json)
records the final outcomes, hashes and limitations.

| Area | What the check verifies | Outcome |
| --- | --- | --- |
| Terran full game, realtime 2v2 | Mining/spending, construction events, workers and army, gas/technology, expansion, combat, native outcome, replay tracker events | Passed; native 2v2 victory/defeat |
| Terran/Protoss/Zerg/Random, four clients | Actual race initialization, mining, race-specific production and expansion; ability/pathing queries; lifecycle events | Passed with research disabled |
| Upgrade research | Same mixed-race build orders with research; two-client control | Failed with four clients; passed with two |
| Five-player FFA, realtime | Fog, enemy vision events, damage/death callbacks, independent policies, batch results | Passed; one native victory and four defeats |
| Failure and cancellation | Exceptions propagate, reports record failures, owned processes exit, no fabricated results | Passed |
| Standard games | Async BotAI vs Computer, standard batch, async two-client game and port release | Passed |
| Replay | Full observer and selected-player results, structure observations, paced bounded preview | Passed after fixing missing ObserverAI callbacks |
| Package | Isolated install, dependencies, wheel/sdist contents, metadata, installed-wheel tests | Passed; see compact evidence for final artifact hashes and test counts |

The installed wheel passes all **214 package tests** outside the checkout on
both Python versions, with bundled assets compared byte-for-byte against source.
The Python 3.10 installed wheel also passes a fresh five-client realtime FFA and
all three replay checks outside the checkout. Replay results agree with the
original game report and independently decoded replay metadata.

The earlier [player-count matrix](player-count-validation.md) covers every
count from two through eight in both timing modes. Those measurements are
retained with their original provenance; this audit does not relabel them as
new runs. The native discovery/readiness bridge and slot-generation algorithm
are unchanged by the release fixes.

## Fixes found during the audit

1. A WebSocket-close exception could skip owned-process cleanup. Cleanup now
   runs in `finally`, including when initial connection setup fails.
2. The standard async launcher did not return automatically reserved ports.
   It now releases only ports it allocated, on both success and failure.
3. Native joins ignored a BotAI's `raw_affects_selection` preference. Each
   client now receives its own setting before joining; the API journal records
   the actual protocol flag. Invalid flags fail before launch.
4. Selected-player replay events called four callbacks absent from upstream
   `ObserverAI`. Replay playback now temporarily binds upstream's no-op defaults
   on the observer instance, preserving overrides and restoring it on exit.

The cleanup regressions failed before the fixes and pass afterwards. Existing
python-sc2 classes and enums retain their identity; no copied Unit/BotAI
implementation or global upstream monkey patch is introduced.

Combined offline/live Python statement-and-branch coverage is **74%** across
the package: `main.py` 88%, `native_session.py` 83%, `replay.py` 93%, and
`standard.py` 100%. Legacy probe/smoke commands have less coverage. These
numbers measure Python execution, not C bridge coverage or SC2 behavior; even
the failed research attempts execute covered Python code.

The dev extra uses pytest 8 (`>=8,<9`). A clean Python 3.10.0 environment with
pytest 9.2 failed inside pytest's own fixture setup before collection; the
compatible test dependency is pinned separately from the runtime dependencies.
Hypothesis 6.168.5 likewise failed internally in five upstream property tests
on Python 3.10.0. Python 3.10's dev extra pins the verified Hypothesis 6.100.0;
all 232 upstream tests then pass without changing their assertions or fixtures.

## Reproduce the audit

```sh
python -m pip install -e '.[dev,build]'
SC2PATH=/nonexistent/mpsc2 python -m pytest --cov=mpsc2 --cov-branch -q

# Extract the exact upstream release checkout, then:
python scripts/validate_upstream.py --source path/to/python-sc2-0875b4b --output reports/upstream-new

python -m mpsc2 doctor
python examples/full_game.py --realtime --teams 7 9 7 9 --output reports/terran-full-new
python scripts/verify_economy_replay.py reports/terran-full-new
python scripts/validate_alpha.py --phase races --skip-research --output reports/races-new
# On 0.3.1a1, omitting --skip-research reproduced the crash; 0.3.1a2 fixes it.
python scripts/validate_alpha.py --phase arena --output reports/ffa-new
python scripts/validate_alpha.py --phase failures --output reports/failures-new
python scripts/validate_alpha.py --phase standard --standard-map path/to/standard.SC2Map --output reports/standard-new
python scripts/validate_alpha.py --phase replay --replay reports/terran-full-new/game.SC2Replay --output reports/replays-new

python -m build --outdir dist/current
python -m twine check dist/current/*
```

Use fresh output directories. The mixed-race check uses normal resources and
production with no debug requests. Failed checks retain their reports. Native
fault tests intentionally raise a policy exception and cancel a running game;
those cases pass only if the expected error propagates and all owned processes
are gone. The upstream comparison refuses a source tree that differs from the
installed pinned dependency.

CI is configured for offline tests and packaging on Linux, macOS and Windows
(Python 3.10/3.13), plus Linux 3.11/3.12. Configuration is not evidence of a
successful remote CI run. SC2 engine checks remain opt-in on the supported Mac.

## Alpha boundaries

- Multiplayer uses the pinned macOS build and bundled maps. Other builds,
  Windows/Linux native hosting, remote hosts and arbitrary maps remain unsupported.
- A bounded race production test is not a complete campaign for every build order,
  ability, team partition or unit interaction. Full Terran combat validation is
  separate from the bounded mixed-race test.
- Human players, external `BotProcess`/ladder services and renderer interaction
  follow the documented upstream routes but are not automated in this audit.
- Independent-player resignation, native process reuse and long-running training
  reliability are not established. Errors propagate instead of becoming results.
- Earlier eight-client startup testing included a timeout; successful subsequent
  runs do not establish a failure rate. See the player-count report for details.

Publishing the repository or uploading a distribution is a separate action.
