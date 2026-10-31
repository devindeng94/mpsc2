# Maps

The package includes two checksum-validated research fixtures:

| Map | Initial setup | Native ending rule |
| --- | --- | --- |
| `MPSC2TeamArena.SC2Map` | Six Marines per player, regardless of selected race | Last surviving team; draw at the fixture time limit |
| `MPSC2Melee.SC2Map` | Race-specific townhall, 12 workers, 50 minerals, resource fields and an expansion site per player | A team loses when all its buildings are destroyed; draw at the time limit |

The launcher prepares slots, spawns and team rules for 2–8 players in a separate
per-run map. It preserves the source map. These fixtures are not ladder maps;
arbitrary maps need the multiplayer handshake and result rules integrated first.

`maps/` holds the repository copies, `src/mpsc2/assets/` holds the installed
package copies, and tests verify that they match. Users do not need to rebuild
or copy maps into SC2. Maintainers can follow the
[deterministic rebuild instructions](../CONTRIBUTING.md#map-maintenance).

The terrain comes from Blizzard's MIT-licensed example `Empty.SC2Map`. See
[provenance and checksum](vendor/NOTICE.md) and its
[license](vendor/LICENSE.s2client-api). Game assets referenced by the maps are
provided by the user's separate SC2 installation.
