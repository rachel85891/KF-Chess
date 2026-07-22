"""auth_command.py: parses Stage D2's new client->server login/signup
command - "AUTH:<username>:<password>" (the CLIENT's own first message,
sent immediately after opening the WebSocket connection, BEFORE the
existing assigned_color response - see
kungfu_chess.client.network.network_game_client's own "STAGE D2 - REAL
AUTH HANDSHAKE" docstring section for the client-side half of this
exchange) - into a structured ParsedAuthCommand.

SRP, and why this is its own module, not inlined in GameServer: this is
a pure parser with no UserRepository/GameSession/ConnectionManager
knowledge - independently unit-testable on its own, exactly like
server/presentation/move_command.py's own identical convention (that
module's own docstring: "independently unit-testable... exactly like
kungfu_chess/notation/algebraic_notation.py... stays independent of
this module in turn").

ONLY THE FIRST COLON AFTER THE USERNAME IS THE DELIMITER (see
kungfu_chess/notation/auth_command_format.py's own docstring for the
formatter-side half of this same contract): `text[len(PREFIX):].split(
":", maxsplit=1)` - a password may itself contain any number of further
colons, all preserved verbatim as part of the password; only a username
containing a colon is unsupported by this grammar (it would be
misparsed as part of the password instead) - an accepted, documented
limitation, not a bug.

WHY THIS NEVER VALIDATES THE PASSWORD AGAINST A REAL ACCOUNT: this
module owns GRAMMAR only (is this text shaped like a real auth
command?), never account-existence/password-correctness (that is
server/persistence/user_repository.py's own job, called from
GameServer - the one component that already holds both a parsed command
and a real UserRepository to check it against, mirroring
move_command.py's own identical "the real-board check lives in
GameServer, not here" split for piece-kind validation).

ONE ERROR TYPE for every malformed reason (mirrors move_command.py's
own "ONE ERROR TYPE" convention exactly): MalformedAuthCommandError is
raised for a missing "AUTH:" prefix, a missing username/password
separator, or an empty username - a caller (GameServer) only ever needs
to catch this one exception type to know "reject this connection",
regardless of which specific part of the grammar was wrong.
"""

from __future__ import annotations

from dataclasses import dataclass

_AUTH_COMMAND_PREFIX = "AUTH:"


class MalformedAuthCommandError(ValueError):
    """Raised by parse_auth_command for any input that isn't a valid
    "AUTH:<username>:<password>" command - see module docstring's "ONE
    ERROR TYPE" section."""


@dataclass(frozen=True)
class ParsedAuthCommand:
    """The structured result of successfully parsing one auth command -
    a plain data holder, per this project's own established
    frozen-dataclass-for-parsed-results convention (e.g.
    server/presentation/move_command.py's own ParsedMoveCommand)."""

    username: str
    password: str


def parse_auth_command(text: str) -> ParsedAuthCommand:
    """Parse one raw auth-command string into a ParsedAuthCommand.

    Args:
        text: The raw text received from a client, expected to be
            "AUTH:<username>:<password>", e.g.
            "AUTH:alice:correct horse battery staple".

    Returns:
        The parsed command.

    Raises:
        MalformedAuthCommandError: If `text` does not start with the
            literal "AUTH:" prefix, has no username/password separator
            after it, or has an empty username (see module docstring's
            "ONE ERROR TYPE" section) - the password itself is never
            validated for emptiness or content here (see module
            docstring's "WHY THIS NEVER VALIDATES..." section).
    """

    if not isinstance(text, str) or not text.startswith(_AUTH_COMMAND_PREFIX):
        raise MalformedAuthCommandError(f"expected an 'AUTH:<username>:<password>' command, got {text!r}")

    remainder = text[len(_AUTH_COMMAND_PREFIX) :]
    parts = remainder.split(":", 1)
    if len(parts) != 2:
        raise MalformedAuthCommandError(f"missing username/password separator in {text!r}")

    username, password = parts
    if not username:
        raise MalformedAuthCommandError(f"username must not be empty in {text!r}")

    return ParsedAuthCommand(username=username, password=password)
