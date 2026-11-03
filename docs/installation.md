# Installation

## Select the right support path

| Use | Requirements |
| --- | --- |
| Import MPSC2 and run offline tests | Python 3.10+; no SC2 installation needed |
| Bundled 2–8-client scenarios | Checksum-pinned macOS Base96883 with `clang`, Windows Base75689/Base93333/Base98370 with 64-bit Python and MinGW-w64 GCC, or Linux x86_64 Base75689 with GCC; compilers needed for 3–8 clients; select an exact Windows build with `sc2_version="Base75689"`, `"Base93333"` or `"Base98370"` |
| Standard one/two-player games | The pinned python-sc2 dependency's supported SC2 installation and maps |
| Replay views of native player IDs ≥4 | The matching supported executable and platform compiler for its observation guard |

The alpha was validated locally on Python 3.10.0 and 3.13.2. Python 3.11/3.12
are configured in offline CI; this is not a claim of live engine validation on
those interpreters. The macOS engine is an x86_64 executable; Apple Silicon
machines need to be able to run that executable through
[Rosetta](https://support.apple.com/en-euro/102527).

## Install the Python package

Clone the actual URL from the repository's GitHub **Code** menu, or download
and extract the source ZIP. Open a terminal in the directory containing
`pyproject.toml`. On macOS/Linux:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
python -m pip check
python -m mpsc2 --version
python -m mpsc2 maps
```

On Windows, for native multiplayer, offline development or the standard-game route
(see the [Windows testing guide](windows.md)):

```powershell
py -3.10 -m venv .venv
.venv\Scripts\python.exe -m pip install .
.venv\Scripts\python.exe -m mpsc2 maps
.venv\Scripts\python.exe -m mpsc2 doctor --mode standard
```

A Windows installation needs the exact supported build and MinGW-w64 GCC for
3–8 clients; follow the [Windows guide](windows.md). Linux x86_64 supports Base75689; follow the [Linux guide](linux.md).
Use `python -m pip install -e '.[dev,build]'` when editing the project. Editable
installs pick up source edits; reinstall after changing package metadata.
See [pip's local-install documentation](https://pip.pypa.io/en/stable/topics/local-project-installs/).

A built wheel can also be installed directly:

```sh
python -m pip install /path/to/mpsc2-0.3.3a2-py3-none-any.whl
```

There is no assumed public PyPI release. Do not rely on `pip install mpsc2`
referring to this project until its publisher confirms that distribution.

## Dependencies

[pyproject.toml](../pyproject.toml) is the dependency source of truth. Pip selects
transitive versions compatible with your interpreter.

| Install | Includes |
| --- | --- |
| `pip install .` or `pip install -r requirements.txt` | `burnysc2==7.3.0` and `mpyq==0.2.5`, plus their dependencies |
| `pip install -e '.[dev,build]'` or `pip install -r requirements-dev.txt` | Editable MPSC2, pytest/coverage, Hypothesis, sc2reader, build and Twine |
| `pip install -e '.[video]'` | Optional local video tooling; unnecessary for games or replay playback |

The requirements files reference this local project rather than duplicate its
version constraints. Run their commands from the repository root.
`requirements-lock.txt` is a **historical Python 3.13 environment snapshot**,
not the current development lock and not a cross-version install recipe.
`requirements-raw.txt` belongs to the separate early protobuf experiment;
normal MPSC2 installation does not use it.

The distribution `burnysc2` installs the `sc2` import namespace. Do not also
install the older distribution named `sc2` in this environment. MPSC2 pins the
upstream version because its lifecycle adapters depend on it.

## Set up SC2 for native multiplayer on macOS

If the 5.0.17/Base98310 update removed your supported engine, use the explicit
[separate compatibility engine](macos-98310-investigation.md#prepare-the-separate-engine)
introduced in 0.3.3a2. It restores the signed Base96883 app and its matching
5.0.15 data selection alongside the retail installation. The Base98310
executable itself did not expose a usable API in local tests.

From your project folder:

```sh
python -m mpsc2 prepare-macos-compat \
  --installation "/Applications/StarCraft II" \
  --destination "$PWD/.mpsc2/StarCraftII-96883"
export SC2PATH="$PWD/.mpsc2/StarCraftII-96883"
python -m mpsc2 doctor --sc2-version Base96883
python -m mpsc2.probe --output reports/compat-engine-probe.json
python examples/minimal_four_player.py
```

Use a new destination and probe output. Setup downloads about 95 MB directly
from Blizzard and verifies every restored app file; the repository contains
metadata, not Blizzard executables. Large game-data files remain shared with
your installed cache. This was tested after an update from 5.0.15; a fresh
installation without the required historical content is not yet validated.
Keep the retail installation available. The setup command prepares files;
the probe and gameplay commands test whether they work on your machine.

Install StarCraft II separately using Blizzard's distribution. Upstream's
[SC2 setup instructions](https://github.com/BurnySc2/python-sc2#starcraft-ii)
cover the normal installation. A current game download is not guaranteed to
contain this alpha's supported historical build.

The default installation path is `/Applications/StarCraft II`. If yours differs,
set `SC2PATH` to the directory containing `Versions` and the game data:

```sh
export SC2PATH="/path/to/StarCraft II"
```

The required executable is:

```text
Versions/Base96883/SC2.app/Contents/MacOS/SC2
```

Its required SHA256 is:

```text
7a8e076ce304d6cc18591eed03bda5ea68a8639826c0b7364de3f53a3da8e0eb
```

A matching build number alone is insufficient. MPSC2 checks the complete
executable hash and refuses other binaries. Ordinary game launches do not
download engines or change versions automatically. Only the explicit setup
command above restores the older app into a new folder. It leaves the retail
executable and build selection intact and preserves Blizzard's app signatures.

Install [Apple's Command Line Tools](https://developer.apple.com/documentation/xcode/installing-the-command-line-tools)
if `clang` is absent:

```sh
xcode-select --install
clang --version
python -m mpsc2 doctor
```

`doctor` detects the platform's installation and reports standard-game and native
multiplayer readiness separately. Its default mode checks the native platform,
compiler, pinned executable/hash and packaged maps. `doctor --mode standard`
checks the upstream installation instead and does not require macOS or clang.
Exit 0 means the selected mode's static checks pass; it does not prove graphics,
local networking or gameplay work. The default mode exits 1 when the platform, pinned executable or required compiler is unavailable.
The maps and C helper sources ship in the package; do not copy maps into the
SC2 installation or precompile the helpers manually.

## Verify a first match

```sh
python examples/multiplayer.py --players 4 --teams 0 0 1 1 --output reports/first-game
python -m mpsc2 replay reports/first-game/game.SC2Replay
```

The match opens four local SC2 processes and closes its owned processes on
completion. Use a different output directory for the next run. A standard
one-BotAI-versus-Computer match needs an ordinary melee map installed separately;
the bundled scenarios accept BotAI participants only.

For failures, consult [troubleshooting](troubleshooting.md). For development
without launching SC2, run `python -m pytest -q` after installing the dev extra.
