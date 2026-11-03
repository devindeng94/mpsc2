"""Experimental versioned local multiplayer service (protocol 1.0)."""
from .backend import Backend, Installation, NativeFactory
from .client import ControlClient, TurnClient, match_spec, sc2_client
from .contract import ServiceError
from .server import LocalServer
from . import multiplayer_pb2
from .bots import play_botais

__all__ = ['Backend', 'Installation', 'NativeFactory', 'ControlClient', 'TurnClient',
           'match_spec', 'sc2_client', 'play_botais', 'ServiceError', 'LocalServer', 'multiplayer_pb2']
