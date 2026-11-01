# Documentation

Start with [installation](installation.md), then run a match from the
[examples guide](../examples/README.md).

| Task | Guide |
| --- | --- |
| Install Python dependencies and SC2 prerequisites | [Installation](installation.md) |
| Detect and test a Windows SC2 installation | [Windows testing](windows.md) |
| Understand supported builds, platforms and APIs | [Compatibility](compatibility.md) |
| Inspect or extend OS/build-specific settings | [Version profiles](version-profiles.md) |
| Adapt a python-sc2 bot | [Migration](migration.md) |
| Configure matches, teams, callbacks and replays | [API reference](api.md) |
| Understand the multiplayer backend | [Architecture](architecture.md) |
| Diagnose installation or game failures | [Troubleshooting](troubleshooting.md) |
| Check current limitations | [Known issues](known-issues.md) |
| Contribute or validate a change | [Contributing](../CONTRIBUTING.md) |
| Upload the repository and prepare a release | [Publishing](publishing.md) |

## Validation records

These are dated measurements, not guarantees for every workload:

- [Windows three-build support, 0.3.2a4](windows-three-build-validation.md):
  Base75689/Base93333/Base98370, live ability-table detection and replay startup.
- [Windows Base98370, 0.3.2a3](windows-98370-validation.md): the updated
  5.0.15 executable, observation guard and installed-data launch behavior.
- [Windows validation, 0.3.2a1](windows-validation.md): independent 2–8-client
  games on Base93333, research, realtime, replays and package checks.
- [Older Windows builds](windows-older-build-validation.md): Base75689 stock
  gameplay and native signature checks; missing Base92440 executable.
- [Research fix, 0.3.1a2](research-validation.md): normal-resource upgrades,
  native callbacks, 2–8 clients, realtime, replay effects and package checks.
- [Alpha audit, 0.3.1a1](alpha-validation.md): upstream compatibility and the
  original research failure, retained as historical evidence.
- [Player-count validation](player-count-validation.md): every count from 2–8
  in both timing modes and one BotAI versus the built-in Computer.
- [Evidence index](../evidence/README.md): public summaries and local raw data.
- [Engineering history through 0.1](engineering-history.md): original prototype
  investigation. Its old API descriptions are not current usage instructions.
