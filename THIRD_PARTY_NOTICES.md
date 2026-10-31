# Third-party notices

MPSC2's original code is licensed under the MIT license in `LICENSE`.

- **python-sc2 / burnysc2 7.3.0**: https://github.com/BurnySc2/python-sc2
  (MIT, Copyright (c) 2017 Hannes Karppila). MPSC2 re-exports its Python APIs
  and adapts its game and observer lifecycle. It remains an installed
  dependency. The original notice is retained in
  `src/mpsc2/licenses/LICENSE.python-sc2` and in built distributions.
- **Blizzard s2client-api terrain fixture**:
  https://github.com/Blizzard/s2client-api/blob/master/maps/Test/Empty.SC2Map
  (MIT, Copyright (c) 2017 Blizzard Entertainment).
  Both MPSC2 maps derive from this terrain fixture. Provenance and checksums
  are in `maps/vendor/NOTICE.md`; the original license is retained in
  `maps/vendor/LICENSE.s2client-api` and `src/mpsc2/licenses/LICENSE.s2client-api`.
- **mpyq** is a dependency for reading MPQ archives. Other transitive
  dependencies retain their respective licenses in their distributions.

StarCraft II is a Blizzard Entertainment game. MPSC2 is an independent research
project and is not affiliated with or endorsed by Blizzard. The SC2 executable,
game assets, account, and installation are not included. The MIT license for
MPSC2 does not license the game itself. Maps reference assets in the user's
separately installed game.
