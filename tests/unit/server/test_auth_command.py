"""Unit tests for server/presentation/auth_command.py - the real WS
auth-command grammar this server understands (Stage D2):
"AUTH:<username>:<password>". No networking, no UserRepository, no
GameServer - this is a pure parser, independently testable, mirroring
server/presentation/move_command.py's own identical SRP convention.
"""

from __future__ import annotations

import pytest

from server.presentation.auth_command import MalformedAuthCommandError, ParsedAuthCommand, parse_auth_command


def test_parses_a_well_formed_auth_command():
    parsed = parse_auth_command("AUTH:alice:correct horse battery staple")

    assert parsed == ParsedAuthCommand(username="alice", password="correct horse battery staple")


def test_a_password_containing_a_colon_is_preserved_verbatim_in_the_parsed_result():
    # Only the FIRST colon after the username is the delimiter - a
    # password containing further colons is not misparsed/truncated.
    parsed = parse_auth_command("AUTH:alice:pass:word:with:colons")

    assert parsed == ParsedAuthCommand(username="alice", password="pass:word:with:colons")


def test_missing_auth_prefix_raises_malformed_auth_command_error():
    with pytest.raises(MalformedAuthCommandError):
        parse_auth_command("alice:secret")


def test_missing_password_separator_raises_malformed_auth_command_error():
    with pytest.raises(MalformedAuthCommandError):
        parse_auth_command("AUTH:alice")


def test_empty_username_raises_malformed_auth_command_error():
    with pytest.raises(MalformedAuthCommandError):
        parse_auth_command("AUTH::secret")


def test_empty_password_is_accepted_as_a_well_formed_but_weak_password():
    # This module only owns GRAMMAR, not password-strength policy (see
    # its own module docstring) - an empty password parses fine; whether
    # it verifies/creates an account is UserRepository's own job.
    parsed = parse_auth_command("AUTH:alice:")

    assert parsed == ParsedAuthCommand(username="alice", password="")


def test_empty_string_raises_malformed_auth_command_error():
    with pytest.raises(MalformedAuthCommandError):
        parse_auth_command("")
