"""auth_command_format.py: formats Stage D2's new client->server
login/signup command in the exact wire grammar
server/presentation/auth_command.py's parse_auth_command already
accepts - "AUTH:<username>:<password>" - the exact reverse of that
parser.

WHY THIS LIVES HERE, NOT IN server/presentation/auth_command.py:
mirrors kungfu_chess/notation/move_command_format.py's own identical
"a client needs to BUILD outgoing commands, but a client must never
import from server/" reasoning verbatim - see that module's own
docstring for the full "server depends on kungfu_chess/, never the
reverse" convention this project already established. Putting the
formatter in this shared package means both
kungfu_chess.client.network.network_game_client (which sends this
message, once, immediately after opening the real WebSocket connection
- see that module's own "STAGE D2 - REAL AUTH HANDSHAKE" docstring
section) and server/presentation/auth_command.py (which parses it) can
each depend on kungfu_chess/notation/ - never on each other - for this
shared, symmetric piece of protocol knowledge.

ONLY THE FIRST COLON AFTER THE USERNAME IS THE DELIMITER (see
server/presentation/auth_command.py's own docstring for the parser-side
half of this same contract): a password MAY contain colons (a real,
common password character) - this formatter never escapes or rejects
one, since parse_auth_command's own `split(":", maxsplit=1)` already
handles it correctly on the receiving end. A username containing a
colon is NOT supported by this wire grammar (it would be misparsed as
part of the password instead) - an accepted, documented limitation,
consistent with kungfu_chess.client.home_screen.prompt_username never
having enforced any character restriction of its own at this stage
either (out of scope to add one just for this).
"""

from __future__ import annotations

_AUTH_COMMAND_PREFIX = "AUTH:"


def format_auth_command(username: str, password: str) -> str:
    """Format a login/signup command in the "AUTH:<username>:<password>"
    grammar server/presentation/auth_command.py's parse_auth_command
    already accepts.

    Args:
        username: The account's username - see module docstring's "ONLY
            THE FIRST COLON..." section for why this must not itself
            contain a colon character.
        password: The account's plaintext password - may contain any
            characters, including colons, verbatim.

    Returns:
        The exact command string, e.g. "AUTH:alice:correct horse
        battery staple".
    """

    return f"{_AUTH_COMMAND_PREFIX}{username}:{password}"
