# Troubleshooting

Start with these commands in the environment where the problem occurs:

```sh
python -m mpsc2 --version
python -m pip check
python -m mpsc2 maps
python -m mpsc2 doctor
```

`doctor` reports the local platform's installation and both backend readiness
sections. Its default exit code follows native multiplayer readiness. Use
`doctor --mode standard` for the upstream route, and `--output reports/doctor.json`
to save a new report. See [Windows testing](windows.md) for the live engine probe.

| Symptom | What to check |
| --- | --- |
| `No module named mpsc2` | Activate the intended environment and install from the repository root with `python -m pip install .`. Use that same Python to run examples. |
| Imports or upstream classes behave unexpectedly | Check for both `sc2` and `burnysc2` distributions. Use a clean environment with the pinned dependency from `pyproject.toml`. |
| Missing executable or unexpected executable SHA256 | Check `SC2PATH`, the exact Base96883 executable and the hash shown by `doctor`. Another build requires backend work; do not bypass the checks. |
| Windows diagnostics mention a Mac app path | Upgrade to 0.3.1a3, verify `python -m mpsc2 --version`, and check `installation.executable`. Set `SC2PATH` to the actual Windows root before starting Python. |
| Missing `clang` or helper compilation failure | Install Apple's Command Line Tools. Inspect the compilation log under the run's `session/bridge/` directory. |
| Bundled-map checksum failure | Reinstall an unchanged package or deliberately rebuild/review the map sources. Arbitrary replacements are unsupported. |
| `FileExistsError` for an output/replay path | Choose a new output directory and replay name. Existing evidence is deliberately preserved. |
| Join barrier timeout | Read `session/bridge/readiness-progress.json` if present, plus the result report and client logs. Retry once in a fresh directory and retain both attempts. Startup reliability remains an alpha limitation. |
| Closed WebSocket / process exited | Inspect the result error, client journal and native logs. A closed connection alone does not identify the underlying cause. |
| Upgrade research crashes with player IDs ≥4 | Check the installed MPSC2 version. The guarded fix is in 0.3.1a2; each affected game's client directory should contain an applied `observation-guard.json`. |
| Replay with selected player ID ≥4 fails | Use 0.3.1a2 and the supported build/compiler. The guarded replay route is build-specific. |
| Notebook reports an already-running event loop | Use `await run_game_async(...)` or `await run_replay_async(...)`. |
| Bots stall or stepped clients disagree | Avoid blocking callbacks and manual `client.step()` calls. Stepped bots must use the same `client.game_step`; the runner owns advancement. |
| `sc2reader` fails on local replay cache handles | Use the supplied replay verification scripts. They read tracker data without the full Battle.net lobby loader. |

A completed game and a passed policy assertion are different results. For
example, the eight-player research regression completes all upgrades but three
players miss their expansions before the fixture ends. See
[known issues](known-issues.md) and the [research report](research-validation.md).

## Report a reproducible issue

Use the GitHub bug-report form. Include Python/MPSC2/SC2 versions, the operating
system, player count, teams, map, timing mode, a minimal command or policy, the
actual error, and `doctor` output when relevant. Include the first failed attempt
as well as any successful retry. Review local paths and player names before
posting excerpts; complete game installations and raw memory dumps are not useful
issue attachments.
