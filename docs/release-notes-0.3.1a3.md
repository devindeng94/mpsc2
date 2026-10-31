# MPSC2 0.3.1a3 — Windows-aware diagnostics

This alpha fixes `mpsc2 doctor` searching for a macOS executable on Windows.
It discovers the installed platform's executable and build, separates standard
game readiness from native multiplayer readiness, and provides a packaged
engine probe and [Windows testing guide](windows.md).

- Run `python -m mpsc2 doctor --mode standard --output reports/doctor.json`
  to inspect a Windows/Linux installation without launching SC2.
- Set `SC2PATH` to the installation root for custom paths; Windows expects
  `Versions/Base<number>/SC2_x64.exe` and `Support64`.
- Run `python -m mpsc2.probe --output reports/engine.json` to record Ping and
  CreateGame responses on the installed engine. Acceptance is not a gameplay test.
- Existing macOS native multiplayer retains its exact executable checks.

**Windows native 2–8-client scenarios are not implemented.** Standard games
continue through burnysc2. This release adds detection and a test workflow;
Windows offline CI is not live SC2 validation. The native bridge and observation
guard remain specific to macOS SC2 Base96883.

Requires Python 3.10+. Install the wheel attached to this release or install
the tagged source. This GitHub release does not publish to PyPI.
