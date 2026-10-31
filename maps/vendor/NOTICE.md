# Base map provenance

`Empty.SC2Map` is Blizzard's example terrain fixture from
[Blizzard/s2client-api, maps/Test/Empty.SC2Map](https://github.com/Blizzard/s2client-api/blob/master/maps/Test/Empty.SC2Map).
Retrieved 2026-10-28.

- Git blob: `16411d15788ecfc73ad0e128316a9fb86f0d6b0a`
- SHA-256: `a69d524e36b4f348ab310dab8d6dae16ba1fd8858f1073f07db9733773c08a46`
- Original license: [LICENSE.s2client-api](LICENSE.s2client-api), MIT, Blizzard Entertainment, 2017.

The generated `../MPSC2TeamArena.SC2Map` retains this map's terrain and dependency
metadata, replaces its MapInfo player slots, replaces the Galaxy script, and
updates its localized name. The builder verifies the base checksum before editing.
Game assets referenced by the map come from the user's installed SC2 game.
