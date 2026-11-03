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
    data_selection: str = 'explicit'
    # (wire ID, burnysc2 ID, API link name, API button name).
    ability_remaps: tuple[tuple[int, int, str, str], ...] = ()
    detect_ability_layout: bool = False

    def executable(self, root: Path) -> Path:
        return root / self.executable_relative_path

    def summary(self) -> dict:
        return {key: value for key, value in asdict(self).items() if key != 'windows_layout'}


_GAMES = (
    GameVersion('4.10.0', 75689, 'B89B5D6FA7CBF6452E721311BFBC6CB2', ('4.10',),
                'PySC2/burnysc2 version tables; local API Ping'),
    GameVersion('5.0.14.93333', 93333, '446907060311FB1CC29EB31E547BB9FD', ('5.0.14',),
                'burnysc2 version table; local API Ping and replay metadata'),
    GameVersion('5.0.15.96883', 96883, 'B49DA51995BA9767F4C624034C211342', ('5.0.15',),
                'macOS compatibility-engine API Ping with matching Base96883 build configuration'),
    GameVersion('5.0.15.98370', 98370, '84197ED58A0329FA79CC9426E07E5FB3', ('5.0.15',),
                'Local Windows API Ping and stepped/realtime replay metadata'),
    GameVersion('5.0.17.98310', 98310, None, ('5.0.17',),
                'macOS .build.info and game UI; API startup failed, no Ping data identifier'),
)
GAME_VERSIONS = MappingProxyType({game.label: game for game in _GAMES})
_ALIASES = MappingProxyType({alias: tuple(g.label for g in _GAMES if alias in g.aliases)
                           for game in _GAMES for alias in game.aliases})

LEGACY_410_ABILITY_REMAPS = (
    (3797, 3966, 'MorphToCollapsibleRockTowerDebrisRampLeftGreen', ''),
    (3798, 3967, 'MorphToCollapsibleRockTowerDebrisRampLeftGreen', 'Cancel'),
    (3799, 3969, 'MorphToCollapsibleRockTowerDebrisRampRightGreen', ''),
    (3800, 3970, 'MorphToCollapsibleRockTowerDebrisRampRightGreen', 'Cancel'),
)

WINDOWS_75689 = NativeProfile(
    id='windows-x86_64-75689-v1', system='Windows', architecture='x86_64', build=75689,
    game_version='4.10.0',
    executable_sha256='b7cac088c463c64ce5ac84acafba546c8c2c13cb7df3613a9c09fb9b0e61f7f9',
    executable_relative_path='Versions/Base75689/SC2_x64.exe', working_directory='Support64',
    backend='windows-local-v1', readiness_strategy='boolean-pairs-two-hold-slots',
    observation_strategy='vectored-exception-r14-rcx-rbx', detect_ability_layout=True,
    helper_sources=('native/windows_bridge.c',), evidence='evidence/2026-11-01/windows-three-build-validation.json',
    windows_layout=WindowsLayout(
        lobby_state=0x3dfd74c, host_flag=0x416d2d0, api_count=0x416d2d4,
        computer_count=0x416d2d8, roster_pointer=0x416da28, roster_count=0x416da30,
        readiness_pointer=0x3dfd7e0,
        lobby_check=InstructionSignature(0xc53657, bytes.fromhex('83fe02770c75064983f9027504b001')),
        readiness_check=InstructionSignature(0xe64caf, bytes.fromhex('4183f8027567')),
        opponent_upgrade=InstructionSignature(0xa76514, bytes.fromhex('410fb6c6b9030000002bc80fb7844bcc000000')),
        own_upgrade=InstructionSignature(0xa764c9, bytes.fromhex('410fb6c60fb78443cc000000')),
        upgrade_cleanup=InstructionSignature(0xa7655c, bytes.fromhex('488d4dd7e89ba3d4ff')),
        upgrade_fault=0xa7651f,
    ),
)
WINDOWS_93333 = NativeProfile(
    id='windows-x86_64-93333-v1', system='Windows', architecture='x86_64', build=93333,
    game_version='5.0.14.93333',
    executable_sha256='e67dcd28e5c5b21d3e4d9e38aada09ed522af28ac0cc5338d709357040493ee0',
    executable_relative_path='Versions/Base93333/SC2_x64.exe', working_directory='Support64',
    backend='windows-local-v1', readiness_strategy='boolean-pairs-two-hold-slots',
    observation_strategy='vectored-exception-r14-rcx-rbx', detect_ability_layout=True,
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
WINDOWS_98370 = NativeProfile(
    id='windows-x86_64-98370-v1', system='Windows', architecture='x86_64', build=98370,
    game_version='5.0.15.98370',
    executable_sha256='c68202849f8e64ed20d15bea0fb89f2c5b94028d075d9848e124a8264d130222',
    executable_relative_path='Versions/Base98370/SC2_x64.exe', working_directory='Support64',
    backend='windows-local-v1', readiness_strategy='boolean-pairs-two-hold-slots',
    observation_strategy='vectored-exception-stack-rax-rdi',
    detect_ability_layout=True,
    data_selection='installed-verified',
    ability_remaps=((4124, 4121, 'MorphToBaneling', 'Baneling'),
                    (4125, 4122, 'MorphToBaneling', 'Cancel'),
                    (4127, 4124, 'MothershipCloak', 'OracleCloakField'),
                    (4129, 4126, 'EnergyRecharge', 'EnergyRecharge'),
                    (4131, 4128, 'SalvageEffect', 'Salvage'),
                    (4133, 4130, 'SalvageSensorTowerRefund', 'Salvage'),
                    (4135, 4132, 'WorkerStopIdleAbilityVespene', 'Gather')),
    helper_sources=('native/windows_bridge.c',), evidence='evidence/2026-11-01/windows-98370-validation.json',
    windows_layout=WindowsLayout(
        lobby_state=0x44690ec, host_flag=0x47d8560, api_count=0x47d8564,
        computer_count=0x47d8568, roster_pointer=0x47d8cb8, roster_count=0x47d8cc0,
        readiness_pointer=0x44691e8,
        lobby_check=InstructionSignature(0xb98ecb, bytes.fromhex('83fd02770c75064983f9027504b001')),
        readiness_check=InstructionSignature(0xd9983f, bytes.fromhex('83f8020f8588000000')),
        opponent_upgrade=InstructionSignature(0x9cf381, bytes.fromhex('0fb6456fb9030000002bc88bc1b9dbd0000066398c47cc000000')),
        own_upgrade=InstructionSignature(0x9cf351, bytes.fromhex('0fb6456fb9dbd0000066398c47cc000000')),
        upgrade_cleanup=InstructionSignature(0x9cf3ba, bytes.fromhex('4c8b1d9f061d03')),
        upgrade_fault=0x9cf393,
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
LINUX_75689 = NativeProfile(
    id='linux-x86_64-75689-v1', system='Linux', architecture='x86_64', build=75689,
    game_version='4.10.0',
    executable_sha256='115f65a49191c504f6336f7d5b7818b23dbba3d7a45cacf9142c86c959abaa41',
    executable_relative_path='Versions/Base75689/SC2_x64', working_directory=None,
    backend='linux-local-v1', readiness_strategy='private-native-count-comparison',
    observation_strategy='private-opponent-field-branch', detect_ability_layout=True,
    helper_sources=('native/linux_bridge.c',),
    helper_source_sha256=('cc2c610a3bb0a055e88d5836e3ef4498e4472a7be2cca030613ea8c44ac38f99',),
    evidence='evidence/2026-11-01/linux-validation.json',
)
NATIVE_PROFILES = MappingProxyType({
    (profile.system, profile.architecture, profile.build): profile
    for profile in (WINDOWS_75689, WINDOWS_93333, WINDOWS_98370, MACOS_96883, LINUX_75689)
})
DEFAULT_NATIVE_BUILDS = MappingProxyType({'Windows': 93333, 'Darwin': 96883, 'Linux': 75689})


class UnsupportedNativeProfile(NotImplementedError):
    """There is no verified native implementation for the requested target."""


def get_game_version(value: str | int, *, system: str | None = None) -> GameVersion:
    """Resolve a canonical label, explicit alias, build number or Base<number>."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError('SC2 version must be a version label or build number')
    key = str(value)
    if key in _ALIASES:
        labels = _ALIASES[key]
        if len(labels) > 1 and system is not None:
            labels = tuple(label for label in labels
                           if find_native_profile(system, GAME_VERSIONS[label].build) is not None)
        if len(labels) != 1:
            raise ValueError(f'Ambiguous SC2 version {value!r}; select an exact version/build or specify its OS')
        key = labels[0]
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
            build = get_game_version(version, system=system).build
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
            {'system': 'Darwin', 'build': 98310, 'game_version': '5.0.17.98310',
             'executable_sha256': 'cbe001a76f5962b207c71179ae86b6129561066d62bc59c0543186f43bfffeb1',
             'standard_api': 'startup failed on tested installation', 'native_multiplayer': 'no profile',
             'note': 'macOS Base98310 did not expose the SC2 API in local tests. Direct API launches '
                     'exited with code 1 before Ping. This is a recorded failure, not proof that every '
                     'installation fails. Base96883 remains the supported macOS native build; '
                     'run python -m mpsc2.probe to retest this installation, or see '
                     'python -m mpsc2 prepare-macos-compat --help for explicit separate-engine setup.',
             'evidence': 'evidence/2026-11-01/macos-98310-startup.json'},
            {'system': 'Windows', 'build': 75689, 'standard_api': 'tested', 'native_multiplayer': 'registered profile',
             'note': 'Engine support uses installed content; historical 4.10 balance data is not guaranteed',
             'evidence': 'evidence/2026-11-01/windows-three-build-validation.json'},
            {'system': 'Windows', 'build': 92440, 'standard_api': 'unverified', 'native_multiplayer': 'no profile',
             'note': 'Local directory was empty; version label/data identifier not inferred'},
            {'system': 'Linux', 'build': 75689, 'standard_api': 'delegated to burnysc2',
             'native_multiplayer': 'registered profile',
             'evidence': 'evidence/2026-11-01/linux-validation.json'},
        ],
    }


def write_windows_header(output: Path, profile=WINDOWS_93333) -> Path:
    """Compile the selected profile's constants into its helper, not env input."""
    require_registered_profile(profile, 'windows-local-v1')
    strategies = {'vectored-exception-r14-rcx-rbx': 1, 'vectored-exception-stack-rax-rdi': 2}
    if (profile.windows_layout is None or profile.readiness_strategy != 'boolean-pairs-two-hold-slots'
            or profile.observation_strategy not in strategies):
        raise UnsupportedNativeProfile('Windows profile requires a compatible implementation strategy')
    lines = ['/* Generated from mpsc2.versions; do not edit. */', '#pragma once',
             f'#define MPSC2_PROFILE_ID "{profile.id}"',
             f'#define MPSC2_OBSERVATION_STRATEGY {strategies[profile.observation_strategy]}']
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
