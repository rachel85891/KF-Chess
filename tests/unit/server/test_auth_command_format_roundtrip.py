"""NEW test file (not an edit to any existing one) proving
kungfu_chess.notation.auth_command_format.format_auth_command and
server.presentation.auth_command.parse_auth_command compose correctly
- mirrors tests/unit/server/test_move_command_format_roundtrip.py's own
identical shape/reasoning, applied to Stage D2's new auth command
instead of the move command.
"""

from __future__ import annotations

import pytest

from kungfu_chess.notation.auth_command_format import format_auth_command
from server.presentation.auth_command import ParsedAuthCommand, parse_auth_command

_CASES = [
    ("alice", "correct horse battery staple"),
    ("bob", "p@ssw0rd!"),
    ("carol", "a password with: colons: in it"),
    ("dave", ""),
]


@pytest.mark.parametrize("username,password", _CASES)
def test_format_then_parse_round_trips_to_the_same_parsed_command(username, password):
    text = format_auth_command(username, password)

    parsed = parse_auth_command(text)

    assert parsed == ParsedAuthCommand(username=username, password=password)
