"""Game metadata and explicitly verified native compatibility profiles.

Data-version identifiers select SC2 content. Executable SHA256 values authorize
native helpers. Neither a known version nor an installed directory authorizes
memory changes. No network access or PySC2 dependency is required.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from types import MappingProxyType

# Retain this module's original python-sc2 compatibility exports and identities.
from sc2.versions import *  # noqa: F401,F403


@dataclass(frozen=True)
class GameVersion:
    label: str
    build: int
    data_version: str | None
    aliases: tuple[str, ...] = ()
    provenance: str = ''


@dataclass(frozen=True)
class InstructionSignature:
    rva: int
    expected: bytes


@dataclass(frozen=True)
class WindowsLayout:
    lobby_state: int
    host_flag: int
    api_count: int
    computer_count: int
    roster_pointer: int
    roster_count: int
    readiness_pointer: int
    lobby_check: InstructionSignature
    readiness_check: InstructionSignature
    opponent_upgrade: InstructionSignature
    own_upgrade: InstructionSignature
    upgrade_cleanup: InstructionSignature
    upgrade_fault: int


@dataclass(frozen=True)
class NativeProfile:
    id: str
    system: str
    architecture: str  # Executable architecture, not the Mac's host CPU.
    build: int
    game_version: str
    executable_sha256: str
    executable_relative_path: str
    working_directory: str | None
    backend: str
    readiness_strategy: str
    observation_strategy: str
    helper_sources: tuple[str, ...]
    evidence: str
    players: tuple[int, ...] = tuple(range(2, 9))
    replay_guard_min_player: int = 4
    windows_layout: WindowsLayout | None = None
    # Legacy macOS helpers retain their verified instructions/offsets in source.
    # Bind that implementation by content, rather than duplicate mutable offsets.
    helper_source_sha256: tuple[str, ...] = ()
    executable_uuid: str | None = None

    def executable(self, root: Path) -> Path:
        return root / self.executable_relative_path

    def summary(self) -> dict:
        return {key: value for key, value in asdict(self).items() if key != 'windows_layout'}


_GAMES = (
    GameVersion('4.10.0', 75689, 'B89B5D6FA7CBF6452E721311BFBC6CB2', ('4.10',),
                'PySC2/burnysc2 version tables; local API Ping'),
    GameVersion('5.0.14.93333', 93333, '446907060311FB1CC29EB31E547BB9FD', ('5.0.14',),
                'burnysc2 version table; local API Ping and replay metadata'),
    GameVersion('5.0.15.96883', 96883, None, ('5.0.15',),
                'Existing macOS validation; data identifier not recorded'),
)
GAME_VERSIONS = MappingProxyType({game.label: game for game in _GAMES})
_ALIASES = MappingProxyType({alias: game.label for game in _GAMES for alias in game.aliases})

WINDOWS_93333 = NativeProfile(
    id='windows-x86_64-93333-v1', system='Windows', architecture='x86_64', build=93333,
    game_version='5.0.14.93333',
    executable_sha256='e67dcd28e5c5b21d3e4d9e38aada09ed522af28ac0cc5338d709357040493ee0',
    executable_relative_path='Versions/Base93333/SC2_x64.exe', working_directory='Support64',
    backend='windows-local-v1', readiness_strategy='boolean-pairs-two-hold-slots',
    observation_strategy='vectored-exception-r14-rcx-rbx',
    helper_sources=('native/windows_bridge.c',), evidence='evidence/2026-10-31/windows-validation.json',
    windows_layout=WindowsLayout(
        lobby_state=0x40381dc, host_flag=0x43a7d90, api_count=0x43a7d94,
        computer_count=0x43a7d98, roster_pointer=0x43a84e8, roster_count=0x43a84f0,
        readiness_pointer=0x4038270,
        lobby_check=InstructionSignature(0xd297f7, bytes.fromhex('83fe02770c75064983f9027504b001')),
        readiness_check=InstructionSignature(0xf48b1f, bytes.fromhex('4183f8020f8589000000')),
        opponent_upgrade=InstructionSignature(0xb3dbe4, bytes.fromhex('410fb6c6b9030000002bc80fb7844bcc000000')),
        own_upgrade=InstructionSignature(0xb3db99, bytes.fromhex('410fb6c60fb78443cc000000')),
        upgrade_cleanup=InstructionSignature(0xb3dc2c, bytes.fromhex('488d4dd7e8bb66ceff')),
        upgrade_fault=0xb3dbef,
    ),
)
MACOS_96883 = NativeProfile(
    id='macos-x86_64-96883-v1', system='Darwin', architecture='x86_64', build=96883,
    game_version='5.0.15.96883',
    executable_sha256='7a8e076ce304d6cc18591eed03bda5ea68a8639826c0b7364de3f53a3da8e0eb',
    executable_relative_path='Versions/Base96883/SC2.app/Contents/MacOS/SC2', working_directory=None,
    backend='macos-96883-v1', readiness_strategy='byte-sum-single-hold-slot',
    observation_strategy='private-seven-byte-branch',
    helper_sources=('native/local_four_bridge.c', 'native/observation_guard.c'),
    helper_source_sha256=('d136951af71ae8e6e070b6c0cb813f7ce0aa61ee76ad58647429697eb9b45fdf',
                          '7b8275a1f79cec21c0a8ba3e50398236de2ce748beb902e759254ffcaff74ef6'),
    executable_uuid='da36f25f-c234-30eb-be05-e4bc16017b08',
    evidence='evidence/2026-10-30/research-fix-validation.json',
)
NATIVE_PROFILES = MappingProxyType({
    (profile.system, profile.architecture, profile.build): profile
    for profile in (WINDOWS_93333, MACOS_96883)
})
DEFAULT_NATIVE_BUILDS = MappingProxyType({'Windows': 93333, 'Darwin': 96883})


class UnsupportedNativeProfile(NotImplementedError):
    """There is no verified native implementation for the requested target."""


def get_game_version(value: str | int) -> GameVersion:
    """Resolve a canonical label, explicit alias, build number or Base<number>."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError('SC2 version must be a version label or build number')
    key = _ALIASES.get(str(value), str(value))
    if key in GAME_VERSIONS:
        return GAME_VERSIONS[key]
    match = re.fullmatch(r'(?:Base)?(\d+)', key)
    if match:
        games = [game for game in GAME_VERSIONS.values() if game.build == int(match[1])]
        if len(games) == 1:
            return games[0]
        if len(games) > 1:
            raise ValueError(f'Build {match[1]} has multiple data versions; select an exact game version')
    raise ValueError(f'Unknown SC2 version {value!r}; known labels: {", ".join(GAME_VERSIONS)}')


def find_native_profile(system: str, build: int, architecture='x86_64') -> NativeProfile | None:
    return NATIVE_PROFILES.get((system, architecture, build))


def get_native_profile(system: str, version=None, architecture='x86_64') -> NativeProfile:
    """Select an explicit verified profile; never fall back from a request."""
    if version is None:
        build = DEFAULT_NATIVE_BUILDS.get(system)
    else:
        try:
            build = get_game_version(version).build
        except ValueError as error:
            raise UnsupportedNativeProfile(str(error)) from error
    profile = find_native_profile(system, build, architecture)
    if profile is None:
        target = f'Base{build}' if build is not None else 'the default build'
        raise UnsupportedNativeProfile(f'No verified native multiplayer profile for {system}/{architecture}/{target}. '
                                       'Known game metadata and standard API support do not authorize native multiplayer.')
    return profile


def require_registered_profile(profile: NativeProfile, backend: str) -> None:
    if (NATIVE_PROFILES.get((profile.system, profile.architecture, profile.build)) != profile
            or profile.backend != backend):
        raise UnsupportedNativeProfile('Native helper requires a registered profile for its backend')


def compatibility_catalog() -> dict:
    """JSON-compatible metadata; this is not an installation/readiness check."""
    return {
        'game_versions': [asdict(game) for game in GAME_VERSIONS.values()],
        'native_profiles': [profile.summary() for profile in NATIVE_PROFILES.values()],
        'default_native_builds': dict(DEFAULT_NATIVE_BUILDS),
        'observations': [
            {'system': 'Windows', 'build': 75689, 'standard_api': 'tested', 'native_multiplayer': 'no profile',
             'note': 'Older engine verified; historical game-data parity unresolved',
             'evidence': 'evidence/2026-10-31/windows-older-build-validation.json'},
            {'system': 'Windows', 'build': 92440, 'standard_api': 'unverified', 'native_multiplayer': 'no profile',
             'note': 'Local directory was empty; version label/data identifier not inferred'},
            {'system': 'Linux', 'build': None, 'standard_api': 'delegated to burnysc2',
             'native_multiplayer': 'no backend'},
        ],
    }


def write_windows_header(output: Path, profile=WINDOWS_93333) -> Path:
    """Compile the selected profile's constants into its helper, not env input."""
    require_registered_profile(profile, 'windows-local-v1')
    if (profile.windows_layout is None or profile.readiness_strategy != 'boolean-pairs-two-hold-slots'
            or profile.observation_strategy != 'vectored-exception-r14-rcx-rbx'):
        raise UnsupportedNativeProfile('Windows profile requires a compatible implementation strategy')
    lines = ['/* Generated from mpsc2.versions; do not edit. */', '#pragma once',
             f'#define MPSC2_PROFILE_ID "{profile.id}"']
    for name, value in vars(profile.windows_layout).items():
        macro = 'MPSC2_' + name.upper()
        if isinstance(value, InstructionSignature):
            lines.append(f'#define {macro}_RVA 0x{value.rva:x}ULL')
            lines.append(f'#define {macro}_BYTES {{{",".join(f"0x{b:02x}" for b in value.expected)}}}')
        else:
            lines.append(f'#define {macro}_RVA 0x{value:x}ULL')
    target = output / 'mpsc2_windows_profile.h'
    target.write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return target
