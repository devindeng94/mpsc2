# Test MPSC2 on Windows

Version **0.3.1a3** fixes `mpsc2 doctor` always looking for the macOS binary.
It finds Windows builds at `Versions\Base<number>\SC2_x64.exe` and reports the
installed build and executable hash. Windows offline tests run in GitHub CI;
SC2 gameplay must be tested on your installed Windows machine.

| Operation | Windows status |
| --- | --- |
| Install/import MPSC2; use BotAI, units, maps and offline utilities | Covered by offline CI |
| Detect SC2 and inspect prerequisites | Supported by this release |
| Standard one/two-player games, including BotAI versus Computer | Delegated to burnysc2; run a live smoke test below |
| Bundled 2–8-client scenarios using `team_ids` | No Windows native backend yet |
| Probe the engine's four-participant CreateGame behavior | Available; reports capability evidence, not a completed multiplayer match |

The native backend changes build-specific process memory using macOS helpers.
A Windows executable needs its own validated backend; changing the file path
or copying the macOS hash/offsets cannot supply it.

## Install or update

In PowerShell, install the published tag into a fresh Python 3.10+ environment:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install "https://github.com/devindeng94/mpsc2/archive/refs/tags/v0.3.1a3.zip"
.venv\Scripts\python.exe -m mpsc2 --version
```

If already working from a clone, update it and reinstall with the same Python:

```powershell
git pull --ff-only
.venv\Scripts\python.exe -m pip install --upgrade .
```

No public PyPI release is assumed. Do not use a bare `pip install mpsc2` to
upgrade this GitHub alpha.

## Locate the installed game

Discovery uses `SC2PATH` first, then Blizzard's
`Documents\StarCraft II\ExecuteInfo.txt`, then
`C:\Program Files (x86)\StarCraft II`. The newest numbered `Base` directory is
reported; an incomplete newest build is reported as an error instead of hidden
by selecting an older one. Windows also needs the installation's `Support64`
directory, as required by the upstream launcher.

For a custom drive, OneDrive Documents folder or an incorrect saved path, set
the root explicitly before starting Python. Replace this example with your
actual folder containing **Versions**, **Support64** and the game data:

```powershell
$env:SC2PATH = "D:\Games\StarCraft II"
.venv\Scripts\python.exe -m mpsc2 doctor --mode standard --output reports/windows-doctor.json
```

No `clang`, `.dylib`, Mac app bundle or macOS executable hash is required for
the standard Windows route. `installation.executable` should end in
`SC2_x64.exe`; `installation.source` explains which path setting was used.
The report always includes both standard and native capability sections.

Exit **0** means static checks passed for the selected mode. It does not prove
graphics, game data, networking or a match will work. Plain `doctor` retains
its default `--mode multiplayer`, so it still exits **1** on Windows while
explaining the missing native backend. Use a new report filename on each run.

## Check the Windows engine's protocol

This command launches one owned SC2 process, records Ping build information,
and tests four API participants in stepped and realtime CreateGame requests,
then tries a standard two-participant 1v1, followed by one API participant with
three Computers if needed. It stops at the first accepted
CreateGame and closes its process. It does not join clients or run policies.
The bundled map resolves even when the current directory is outside a clone.

```powershell
.venv\Scripts\python.exe -m mpsc2.probe --output reports/windows-engine.json --timeout 90
```

An `InvalidPlayerSetup` response with `Only 1v1 is supported when using multiple
agents` is useful evidence of an engine restriction. It is not a failed path
lookup. Conversely, an accepted CreateGame alone does not establish four-client
support. Exit 0 means the probe completed; inspect each case's `accepted`,
`error_name` and `error_details` fields. Exit 1 means the probe could not complete.

## Run a normal economy match

Use a source checkout for the examples. Install an ordinary melee map separately;
the bundled MPSC2 scenarios require their multiplayer handshake and cannot
substitute for this standard-game test. This follows
[python-sc2's installation and map setup](https://github.com/BurnySc2/python-sc2#starcraft-ii).

```powershell
.venv\Scripts\python.exe examples/versus_computer.py "D:\SC2Maps\YourMeleeMap.SC2Map" --seconds 60 --output reports/windows-economy
```

The example checks mining, worker training, supply construction and an active
built-in opponent, and saves a replay and `validation.json`. Add `--realtime`
and choose another output directory to test realtime execution. An assertion
failure is evidence to investigate, even if the game window opened.

For follow-up diagnosis, retain the MPSC2 version, doctor report, engine probe,
command, traceback and economy validation. Review local paths before posting
them in an issue. The reports contain installation metadata and hashes; the
game executable is not needed as an issue attachment.
