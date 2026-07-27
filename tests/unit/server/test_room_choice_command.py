"""Unit tests for server/presentation/room_choice_command.py - the real
post-AUTH client-choice grammar this server will understand (Stage F3):
"PLAY" / "CREATE_ROOM" / "JOIN_ROOM:<code>". No networking, no
SessionCoordinator, no GameServer - this is a pure parser, independently
testable, mirroring server/presentation/auth_command.py's own identical
SRP convention.
"""

from __future__ import annotations

import pytest

from server.presentation.room_choice_command import (
    CreateRoomCommand,
    JoinRoomCommand,
    MalformedRoomChoiceCommandError,
    PlayCommand,
    parse_room_choice_command,
)


def test_parses_play():
    assert parse_room_choice_command("PLAY") == PlayCommand()


def test_parses_create_room():
    assert parse_room_choice_command("CREATE_ROOM") == CreateRoomCommand()


def test_parses_join_room_with_a_code():
    assert parse_room_choice_command("JOIN_ROOM:ABCDEF") == JoinRoomCommand(code="ABCDEF")


def test_a_code_containing_a_colon_is_preserved_verbatim_after_the_first_colon():
    # Only the FIRST colon after "JOIN_ROOM" is the delimiter - mirrors
    # auth_command.py's own identical "only the first colon delimits"
    # convention for passwords.
    parsed = parse_room_choice_command("JOIN_ROOM:AB:CD")

    assert parsed == JoinRoomCommand(code="AB:CD")


def test_empty_string_raises_malformed_room_choice_command_error():
    with pytest.raises(MalformedRoomChoiceCommandError):
        parse_room_choice_command("")


def test_unrelated_text_raises_malformed_room_choice_command_error():
    with pytest.raises(MalformedRoomChoiceCommandError):
        parse_room_choice_command("WQe2e5")


def test_join_room_with_no_colon_at_all_raises_malformed_room_choice_command_error():
    with pytest.raises(MalformedRoomChoiceCommandError):
        parse_room_choice_command("JOIN_ROOM")


def test_join_room_with_an_empty_code_raises_malformed_room_choice_command_error():
    with pytest.raises(MalformedRoomChoiceCommandError):
        parse_room_choice_command("JOIN_ROOM:")


def test_lowercase_play_is_rejected_exact_match_only_no_case_insensitivity():
    # Unlike the move/jump-command grammar (the ONE case-insensitive
    # grammar in this protocol - see move_command.py's own docstring),
    # AUTH/PLAY/CREATE_ROOM/JOIN_ROOM are all-caps by convention with no
    # case-insensitive matching - a deliberate choice, not an oversight.
    with pytest.raises(MalformedRoomChoiceCommandError):
        parse_room_choice_command("play")
