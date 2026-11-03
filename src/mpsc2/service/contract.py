"""Protocol validation independent of an engine, transport or native adapter."""
from __future__ import annotations

import math
import re
from google.protobuf.message import Message
from s2clientprotocol import sc2api_pb2 as api
from . import multiplayer_pb2 as pb

MAX_FRAME = 32 * 1024 * 1024
READS = frozenset(('ping', 'game_info', 'data', 'query', 'observation'))
GAMEPLAY = READS | {'action', 'step', 'save_replay', 'leave_game', 'quit'}
FEATURES = frozenset(('independent-clients.v1', 'fixed-teams.v1', 'shared-vision.v1',
                      'raw-interface.v1', 'stepped-clock.v1', 'realtime-clock.v1',
                      'joint-turns.v1', 'own-upgrades.v1', 'save-replay.v1'))


class ServiceError(Exception):
    def __init__(self, code, message, *, capability='', retry_safe=False):
        super().__init__(message)
        self.proto = pb.Error(code=code, message=message, capability=capability, retry_safe=retry_safe)


def require(condition, message, code=pb.ERROR_INVALID_REQUEST):
    if not condition:
        raise ServiceError(code, message)


def copy(message):
    result = type(message)()
    result.CopyFrom(message)
    return result


def canonical(message: Message):
    """Compare parsed known fields, ignoring field ordering and unknown fields."""
    result = copy(message)
    result.DiscardUnknownFields()
    return result.SerializeToString(deterministic=True)


def present(message, *fields):
    require(all(message.HasField(f) for f in fields), 'Missing fields: ' + ', '.join(fields))


def identifier(value):
    require(bool(re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value)), 'Invalid identifier')


def validate_spec(spec):
    present(spec, 'engine', 'map', 'teams', 'clock', 'transport', 'random_seed')
    identifier(spec.engine.installation_id)
    identifier(spec.map.artifact_id)
    require(len(spec.map.sha256) == 32 and bool(spec.map.rules_contract), 'Map hash and rules contract required')
    require(spec.players, 'At least one player required')
    require(len({p.slot_id for p in spec.players}) == len(spec.players), 'Duplicate player slots')
    for player in spec.players:
        identifier(player.slot_id)
        present(player, 'team_id', 'kind', 'race')
        require(player.kind in (pb.PLAYER_AGENT, pb.PLAYER_COMPUTER, pb.PLAYER_HUMAN), 'Invalid player kind')
        require(player.race in (1, 2, 3, 4), 'Invalid race')
        require(len(player.name) <= 128, 'Player name too long')
        if player.kind == pb.PLAYER_AGENT:
            require(player.HasField('interface_options') and player.interface_options.raw, 'Agents require raw observations')
    require(any(p.kind == pb.PLAYER_AGENT for p in spec.players), 'At least one agent required')
    present(spec.teams, 'vision', 'shared_unit_control', 'allied_victory')
    require(spec.teams.vision in (pb.TEAM_VISION_INDIVIDUAL, pb.TEAM_VISION_SHARED), 'Invalid team vision')
    require(spec.clock in (pb.CLOCK_STEPPED, pb.CLOCK_REALTIME), 'Invalid clock')
    require(spec.transport in (pb.TRANSPORT_SC2_COMPAT, pb.TRANSPORT_JOINT_TURN), 'Invalid transport')
    if spec.clock == pb.CLOCK_STEPPED:
        require(1 <= spec.step_count <= 224, 'step_count must be 1..224')
        require(100 <= spec.round_timeout_ms <= 3600000, 'round_timeout_ms must be 100..3600000')
    else:
        require(spec.transport == pb.TRANSPORT_SC2_COMPAT, 'Realtime joint turns are unavailable', pb.ERROR_CAPABILITY_UNAVAILABLE)
    require(math.isfinite(spec.game_time_limit_seconds) and 1 <= spec.game_time_limit_seconds <= 86400,
            'game_time_limit_seconds must be 1..86400')
    if spec.engine.HasField('required_executable_sha256'):
        require(len(spec.engine.required_executable_sha256) == 32, 'Invalid executable hash')
    require(len(spec.required_capabilities) <= 64, 'Too many required capabilities')
    return required_features(spec)


def required_features(spec):
    required = set(spec.required_capabilities) | {'independent-clients.v1', 'fixed-teams.v1', 'raw-interface.v1'}
    required.add('stepped-clock.v1' if spec.clock == pb.CLOCK_STEPPED else 'realtime-clock.v1')
    if spec.transport == pb.TRANSPORT_JOINT_TURN:
        required.add('joint-turns.v1')
    if spec.teams.vision == pb.TEAM_VISION_SHARED:
        required.add('shared-vision.v1')
    if spec.teams.shared_unit_control:
        required.add('shared-control.v1')
    return required


def operation(request):
    return request.WhichOneof('request')


def validate_action(actions):
    # Scenario handshake chat is an administrative map interface. Agents may
    # issue ordinary chat, but cannot reconfigure native slot or ready state.
    for action in actions.actions:
        if action.HasField('action_chat'):
            require(not action.action_chat.message.startswith('MPSC2-'),
                    'Reserved scenario command', pb.ERROR_UNSUPPORTED_MESSAGE)


def validate_read(request, loop=None, *, realtime=False):
    name = operation(request)
    require(name in READS, 'Only Ping/GameInfo/Data/Query/Observation are allowed', pb.ERROR_UNSUPPORTED_MESSAGE)
    if name == 'observation':
        require(not request.observation.disable_fog, 'Agent observations cannot disable fog', pb.ERROR_UNAUTHORIZED)
        if not realtime and request.observation.HasField('game_loop'):
            require(loop is not None and request.observation.game_loop <= loop,
                    'Future observations would block stepped progress')
    return name
