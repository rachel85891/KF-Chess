"""Unit tests for kungfu_chess/notation/auth_command_format.py - the
client-side formatter for Stage D2's new "AUTH:<username>:<password>"
wire message, mirroring kungfu_chess/notation/move_command_format.py's
own "format lives in the shared kungfu_chess/notation/ package, a
client must never import from server/" convention (see that module's
own docstring for the shared reasoning, which applies identically
here).
"""

from __future__ import annotations

from kungfu_chess.notation.auth_command_format import format_auth_command


def test_formats_a_username_and_password_with_the_auth_prefix():
    text = format_auth_command("alice", "correct horse battery staple")

    assert text == "AUTH:alice:correct horse battery staple"


def test_a_password_containing_a_colon_is_preserved_verbatim():
    # The server-side parser only splits on the FIRST colon after the
    # username (server/presentation/auth_command.py's own docstring) -
    # this proves the formatter doesn't do anything (e.g. escaping)
    # that would break that contract.
    text = format_auth_command("alice", "pass:word:with:colons")

    assert text == "AUTH:alice:pass:word:with:colons"
