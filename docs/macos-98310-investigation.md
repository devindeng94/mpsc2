# macOS 5.0.17 / Base98310 investigation

**Status: a separate Base96883 compatibility engine is available in 0.3.3a2.**
The updated Base98310 executable itself remains unsupported. The compatibility
route restores 5.0.15 research sessions alongside the 5.0.17 retail installation;
it does not run the new engine or its balance data.


## Prepare the separate engine

From the project folder, with MPSC2 0.3.3a2 installed:

```sh
python -m mpsc2 prepare-macos-compat \
  --installation "/Applications/StarCraft II" \
  --destination "$PWD/.mpsc2/StarCraftII-96883"
export SC2PATH="$PWD/.mpsc2/StarCraftII-96883"
python -m mpsc2 doctor --sc2-version Base96883
python -m mpsc2.probe --output reports/compat-engine-probe.json
python examples/minimal_four_player.py
```

Use a fresh destination. Set `SC2PATH` in each shell or process that should use
this engine. Existing `BotAI`, `run_game`, team IDs, realtime mode and replay
interfaces stay the same. There is no implicit fallback when Base98310 is
selected. The function is also available as
`mpsc2.compat_engine.prepare_macos_compat(installation, destination, cache=None)`.

Setup restores the complete signed Base96883 app, reusing 118 matching local
files and downloading 11 older files (about 95 MB total) from Blizzard's CDN.
Pinned metadata verifies source files, archive ranges, BLTE checksums and final
SHA256 values. The original app signature is retained; no re-signing or system
security change is required. The package distributes metadata and code only.
An optional `--cache` reuses verified downloads.

The compatibility root owns its build configuration and `.build.info`, selecting
build key `275c3e0594f089a29a5d7b1f470511a3`. The API reports **5.0.15.96883** and
data version **B49DA51995BA9767F4C624034C211342**. Large content files remain linked
to the retail content cache. The retail executable and build selection are
unchanged. Keep the retail installation available; historical content removed
by a later update can break the compatibility root. A fresh 5.0.17 installation
without historical content has not been validated.

Preparation does not launch SC2 or certify gameplay. Its receipt explicitly
records `live_validation: "not run by this command"`. Run the probe and a game
on the target machine. `doctor` reports the explicit compatibility selection
and still treats readiness as static prerequisite checks.

The probe uses the unmodified stock protocol. Its four-participant CreateGame
rejections are expected; a successful Ping and two-participant creation establish
API startup. The multiplayer example then exercises MPSC2's native bridge.

Recovering only the older executable was insufficient: mismatched app resources
failed signature verification. Restoring the complete signed app fixed that,
but leaving the new retail build metadata selected still prevented API startup.
Selecting the matching historical build resolved startup without modifying
Blizzard's executable.

## Investigation of the updated executable

On 2026-11-01, the updated macOS installation contained Base98310 and reported
5.0.17.98310 in both `.build.info` and the game UI. The old Base96883 directory
remained, but its executable had been removed. The app's Info.plist still
contained an older version label, so it was not used to identify the engine.

| Identity | Measured value |
| --- | --- |
| Executable | `Versions/Base98310/SC2.app/Contents/MacOS/SC2` |
| Architecture | x86_64, tested on Apple Silicon |
| Size | 78,718,656 bytes |
| SHA256 | `cbe001a76f5962b207c71179ae86b6129561066d62bc59c0543186f43bfffeb1` |
| Mach-O UUID | `71ad15db-f69b-3aa8-b842-2d868931f0db` |
| API-reported build/data version | Unavailable: no Ping response |

## What was tested

- The existing four-client launcher: it could not find its required Base96883
  executable. Its native helpers were never loaded into Base98310.
- An unmodified engine through the stock protocol probe: no API connection,
  Ping, CreateGame or JoinGame was reached.
- Direct launches with Blizzard's documented `-listen 127.0.0.1 -port ...`
  arguments, windowed Metal rendering, and variations in temporary-directory,
  verbose, window-size, working-directory, launch, data-version and headless
  settings. Each direct test exited with code 1 before opening the API port.
- A clean launch with no other SC2 process running: the same early exit.
- The official SC2Switcher launcher: it preserved the API arguments and
  started the normal login UI, but the requested API port stayed unavailable.
- Debugger-assisted startup: the ordinary login UI appeared, but the requested
  API port remained unavailable. A separate inspection after initialization
  confirmed the same absence of API protocol markers described below.
- The revised MPSC2 probe: it records `SC2LaunchError`, the process exit code,
  `api_connected: false` and an empty case list, instead of a generic timeout.

Read-only inspection of the unpacked executable's `__TEXT` segment found no
`sc2api.proto`, `RequestCreateGame`, `RequestJoinGame`, `RequestPing` or
`ResponsePing` markers. Other protobuf descriptors were present, as were
generic `listen`/`port` option registrations. This suggests the SC2 API
implementation may be absent or disabled in this binary. It is **not** proof
of Blizzard's build configuration or the precise cause of the early exit.

The launch arguments follow
[Blizzard's protocol documentation](https://github.com/Blizzard/s2client-proto/blob/master/docs/protocol.md).
No public source located during this investigation established a replacement
API switch for Base98310.

## What MPSC2 now reports

`mpsc2 versions` recognizes the game label as metadata but grants no native
support. `mpsc2 doctor` warns only when the OS, build and executable checksum
match this measured failure. Its standard `ready` field still describes
static installation prerequisites; it does not confirm that the API starts.
The warning does not prevent retesting:

```sh
python -m mpsc2 doctor --output reports/mac-update-doctor.json
python -m mpsc2.probe --timeout 30 --output reports/mac-update-engine.json
```

Use new output paths for each attempt. A failed startup is separate from a
CreateGame rejection: changing multiplayer lobby addresses cannot fix an API
that never starts. No Base98310 memory patch or re-signing was added. The separate compatibility
engine is explicitly selected and never replaces the retail executable. The installed executable's checksum was unchanged
after testing.

macOS native support remains pinned to the validated Base96883 executable.
The separate-engine setup above restores that profile after the tested retail
update. Existing Windows and Linux profiles and native helper sources are
unchanged. Full-game, realtime, research and replay tests on the actual
Base98310 executable remain unavailable because its API did not start.

The public [original measurement summary](../evidence/2026-11-01/macos-98310-startup.json)
preserves the initial failure. A separate
[compatibility validation record](../evidence/2026-11-01/macos-compat-engine.json)
records the recovered engine's results. Neither record includes game binaries
or memory dumps.

## Direct-launch retest on 2026-11-02

Battle.net is not a requirement for MPSC2 or python-sc2 API games. A fresh
direct-launch comparison on the same Mac again reached Ping and CreateGame on
Base96883 without Battle.net, while the actual Base98310 executable exited with
code 1 before Ping. Capturing the upstream launcher's stderr did not resolve
Base98310 startup. A separate complete copy of the Base98310 app with historical
build metadata also failed before Ping. The retail app and its metadata remain
unchanged.

Changing `-dataDir` alone did not switch the working engine to 5.0.17 data:
its Ping still reported 5.0.15.96883 and the historical data hash. That experiment
does not establish compatibility with new balance data. The separate copy was
used to test historical build selection without changing the retail install.

The macOS application launcher was also tried without Battle.net. It returned
success, but the probe never connected and did not observe a persistent engine
process; launcher success is not evidence of game or API startup. The separate
Battle.net UI route was not run because app control was unavailable. A public
[Mac project reports that route](https://github.com/golergka/jev-plays-starcraft-2/blob/main/docs/PROCEDURE.md),
but the cited procedure does not establish support for this exact Base98310
executable.

Comparison of the complete executable files gives stronger evidence than a
launch timeout alone:

| Marker | Working Base96883 | Base98310 |
| --- | ---: | ---: |
| `SC2API` | 458 | 0 |
| `sc2api.proto` | 2 | 0 |
| `RequestPing` | 3 | 0 |
| `RequestCreateGame` | 3 | 0 |
| `RequestJoinGame` | 3 | 0 |
| `bgs.protocol` (comparison control) | 512 | 512 |

The previous initialized-memory capture shows the same absence of API markers.
The installed build's official manifest lists one Mac game executable across
regions and no separate SC2 API library. These measurements suggest that this
binary lacks the API implementation; they do not prove Blizzard's compile flags
or rule out every possible implementation. No replacement launch switch or
verified Base98310 API build was found. Existing multiplayer bridge offsets
cannot be applied to this different executable, and a bridge alone would not
provide the missing observation/action interface.

The probe now supports an API-reported build requirement:

```sh
SC2PATH="/Applications/StarCraft II" python -m mpsc2.probe \
  --expected-base-build 98310 --timeout 30 \
  --output reports/base98310-retest.json
```

It stops before CreateGame if a different engine answers. For an engine already
started with API arguments by any launcher, a connection-only check is available:

```sh
python -m mpsc2.probe --attach-port 5001 --expected-base-build 98310 \
  --timeout 10 --output reports/base98310-connection.json
```

This sends only Ping to localhost, closes its own socket, and sends no game or
process-control requests. It does not start Battle.net, require its use, or
enable an API that the engine has not opened. Live testing against Base96883
confirmed reconnection, wrong-build rejection, and survival of the game process
after each disconnect. Mock protocol tests do not count as Base98310 support.

See the [retest record](../evidence/2026-11-02/macos-98310-retest.json), including
the failed initial control launch, test-harness errors and successful retries.
Native Base98310 gameplay remains unachieved. The existing explicitly selected
Base96883 engine remains the validated Mac route.
