"""python-sc2 maps plus bundled multiplayer scenarios, independent of cwd."""
from pathlib import Path

from sc2.maps import Map
from sc2 import maps as upstream

BUILTIN_NAMES = ('MPSC2TeamArena', 'MPSC2Melee')


def _absolute_map(path: Path) -> Map:
    # Map.__init__ probes Paths.MAPS even for an unrelated absolute path.
    # Set its two public fields directly so packaged maps work without an SC2
    # installation (including documentation, CI and remote orchestration).
    result = Map.__new__(Map)
    result.path = path.resolve(strict=True)
    result.relative_path = result.path
    return result


def get(name: str | Path) -> Map:
    """Resolve a bundled name, existing SC2Map path, or installed SC2 map name."""
    path = Path(name).expanduser()
    if path.is_file():
        if path.suffix.lower() != '.sc2map':
            raise ValueError(f'Expected an .SC2Map file: {path}')
        return _absolute_map(path)
    stem = path.stem if path.suffix.lower() == '.sc2map' else str(name)
    if path.name == str(name) and stem in BUILTIN_NAMES:
        return _absolute_map(Path(__file__).with_name('assets') / f'{stem}.SC2Map')
    if isinstance(name, Path) or path.is_absolute() or len(path.parts) > 1:
        raise FileNotFoundError(path)
    return upstream.get(str(name))


def available() -> tuple[str, ...]:
    """Bundled maps; no game installation or SC2 process is needed."""
    return BUILTIN_NAMES


__all__ = ['Map', 'get', 'available']
