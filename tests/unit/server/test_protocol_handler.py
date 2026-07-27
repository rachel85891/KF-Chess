"""Unit tests for server/presentation/protocol_handler.py's
ProtocolHandler - no networking, no GameSession/ConnectionManager, no
GameServer (see that class's own module docstring's "ZERO
GameSession/ConnectionManager/EventBus KNOWLEDGE" section) - a bare
ProtocolHandler() is constructed directly throughout.

This file is new, net-new coverage for a class that had none of its
own dedicated unit tests before Stage F3 (confirmed via `find tests
-iname "*protocol_handler*"` before creating this file) - it does NOT
attempt to cover every pre-existing method exhaustively, only the
Stage F3 room-choice parsing/formatting additions this stage adds.
"""

from __future__ import annotations

import pytest

from server.presentation.protocol_handler import ProtocolHandler
from server.presentation.room_choice_command import (
    CreateRoomCommand,
    JoinRoomCommand,
    MalformedRoomChoiceCommandError,
    PlayCommand,
)


def test_parse_incoming_room_choice_delegates_for_play():
    handler = ProtocolHandler()

    assert handler.parse_incoming_room_choice("PLAY") == PlayCommand()


def test_parse_incoming_room_choice_delegates_for_create_room():
    handler = ProtocolHandler()

    assert handler.parse_incoming_room_choice("CREATE_ROOM") == CreateRoomCommand()


def test_parse_incoming_room_choice_delegates_for_join_room():
    handler = ProtocolHandler()

    assert handler.parse_incoming_room_choice("JOIN_ROOM:AB3XQ9") == JoinRoomCommand(code="AB3XQ9")


def test_parse_incoming_room_choice_reraises_malformed_room_choice_command_error():
    handler = ProtocolHandler()

    with pytest.raises(MalformedRoomChoiceCommandError):
        handler.parse_incoming_room_choice("not a real choice")


def test_format_room_created():
    handler = ProtocolHandler()

    assert handler.format_room_created("ABCDEF") == "room_created:ABCDEF"


def test_format_room_joined_as_guest():
    handler = ProtocolHandler()

    assert handler.format_room_joined("guest") == "room_joined:guest"


def test_format_room_joined_as_viewer():
    handler = ProtocolHandler()

    assert handler.format_room_joined("viewer") == "room_joined:viewer"


def test_format_room_not_found():
    handler = ProtocolHandler()

    assert handler.format_room_not_found() == "room_not_found"
