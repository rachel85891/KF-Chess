"""room_choice_command.py: parses Stage F3's new post-AUTH client
choice - "PLAY" / "CREATE_ROOM" / "JOIN_ROOM:<code>" (the CLIENT's own
first message AFTER a successful AUTH, before the existing
assigned_color/room_created/room_joined response - a future stage,
F4, will make this choice a real branch inside GameServer.
handle_connection, calling SessionCoordinator.find_match/create_room/
join_room; this module owns none of that, only the grammar) - into one
of three structured commands.

SRP, and why this is its own module, not folded into
parse_incoming_command: this is a pure parser with no
SessionCoordinator/GameServer/networking knowledge - independently
unit-testable on its own, exactly like server/presentation/
auth_command.py's own identical convention. It is also its own
DISTINCT method/module from parse_incoming_command (the existing move/
jump dispatcher), for the identical reason parse_incoming_auth_command
already is: this message occurs at its own distinct point in the
connection lifecycle (after AUTH, before assigned_color/room_created/
room_joined), never interleaved with a move/jump command, so there is
no shared dispatch decision to make between this grammar and that one -
folding them together would only entangle two grammars that never
actually compete to parse the same message.

ONLY THE FIRST COLON AFTER "JOIN_ROOM" IS THE DELIMITER: mirrors
auth_command.py's own "only the first colon is the delimiter"
convention exactly - `text[len(_JOIN_ROOM_PREFIX):]`, taken whole, not
re-split - a code containing a colon is preserved verbatim (an
accepted, documented limitation, not a bug, identical in spirit to
auth_command.py's own "a username containing a colon is unsupported"
note, just applied to a room code instead of a username).

WHY THIS NEVER VALIDATES THE CODE AGAINST ROOM_CODE_ALPHABET/
ROOM_CODE_LENGTH (server/application/room.py's own constants) - A
DELIBERATE DECISION, NOT AN OVERSIGHT: this module owns GRAMMAR only
(is this text shaped like "JOIN_ROOM:<something>", with a non-empty
code?), never whether that code matches the real alphabet/length, or
names a real, currently-tracked room (that is a SessionCoordinator/
GameServer concern, Stage F4's own job - the one component that will
hold both a parsed command and a real SessionCoordinator to check it
against). This mirrors move_command.py's own identical "the real-board
check lives in GameServer, not here" split for piece-kind validation
exactly. It is ALSO a hard dependency-direction requirement, not merely
a stylistic preference: this project's own established rule is that
server/application/ imports from server/presentation/, never the
reverse (re-verified directly via `grep -rn "^from server.application"
server/presentation/` before writing this module, and again before
every commit in this stage - it returns nothing) - importing
ROOM_CODE_ALPHABET/ROOM_CODE_LENGTH from server/application/room.py
into this file would itself violate that rule, entirely independent of
whether validating here would otherwise be a reasonable design choice.

ONE ERROR TYPE for every malformed reason (mirrors auth_command.py's/
move_command.py's own "ONE ERROR TYPE" convention exactly):
MalformedRoomChoiceCommandError is raised for unrecognized text, a
"JOIN_ROOM" with no colon at all, or a "JOIN_ROOM:" with an empty code
after the colon - a caller (GameServer, in Stage F4) only ever needs to
catch this one exception type to know "this connection sent something
that isn't a valid post-AUTH choice", regardless of which specific
reason applied.

EXACT-CASE MATCH ONLY, NO CASE-INSENSITIVITY (a deliberate choice,
documented here since it could otherwise read as an oversight):
"PLAY"/"CREATE_ROOM"/"JOIN_ROOM:<code>" are recognized only in the
exact case shown - AUTH/PLAY/CREATE_ROOM/JOIN_ROOM are all-caps by
this protocol's own existing convention (see auth_command.py's own
"AUTH:" prefix, matched the same way). The move/jump-command grammar
(move_command.py's own parse_move_command) is the ONE case-insensitive
grammar in this whole protocol, and that is documented as its own,
narrow choice in that module - it is not a project-wide convention this
module needs to match.

THREE DISTINCT DATACLASSES, NOT ONE WITH A DISCRIMINANT FIELD: mirrors
this project's existing `Union[ParsedMoveCommand, ParsedJumpCommand]`
return-type convention for parse_incoming_command - a caller
type-narrows via `isinstance`/structural matching on the concrete type
itself, rather than branching on a string/enum discriminant field
nested inside one shared shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

_PLAY_COMMAND = "PLAY"
_CREATE_ROOM_COMMAND = "CREATE_ROOM"
_JOIN_ROOM_PREFIX = "JOIN_ROOM:"


class MalformedRoomChoiceCommandError(ValueError):
    """Raised by parse_room_choice_command for any input that isn't a
    valid "PLAY" / "CREATE_ROOM" / "JOIN_ROOM:<code>" command - see
    module docstring's "ONE ERROR TYPE" section."""


@dataclass(frozen=True)
class PlayCommand:
    """The parsed result of a "PLAY" choice - no fields: there is
    nothing further to parse out of this literal (mirrors
    OPPONENT_RECONNECTED_MESSAGE's own "bare literal, no detail needed"
    shape, applied here to an incoming command instead of an outgoing
    message)."""


@dataclass(frozen=True)
class CreateRoomCommand:
    """The parsed result of a "CREATE_ROOM" choice - no fields, for the
    same reason as PlayCommand above."""


@dataclass(frozen=True)
class JoinRoomCommand:
    """The parsed result of a "JOIN_ROOM:<code>" choice - a plain data
    holder, per this project's own established frozen-dataclass-for-
    parsed-results convention (e.g. server/presentation/auth_command.py's
    own ParsedAuthCommand). `code` is grammar-only, unvalidated against
    any alphabet/length/registry - see module docstring's "WHY THIS
    NEVER VALIDATES THE CODE..." section."""

    code: str


def parse_room_choice_command(text: str) -> Union[PlayCommand, CreateRoomCommand, JoinRoomCommand]:
    """Parse one raw post-AUTH choice string into a structured command.

    Args:
        text: The raw text received from a client, expected to be
            exactly "PLAY", exactly "CREATE_ROOM", or "JOIN_ROOM:<code>"
            with a non-empty code, e.g. "JOIN_ROOM:AB3XQ9".

    Returns:
        A PlayCommand, CreateRoomCommand, or JoinRoomCommand.

    Raises:
        MalformedRoomChoiceCommandError: If `text` is not a real string,
            is not exactly "PLAY"/"CREATE_ROOM", and is not a
            "JOIN_ROOM:" prefix followed by a non-empty code (see
            module docstring's "ONE ERROR TYPE" and "EXACT-CASE MATCH
            ONLY" sections).
    """

    if not isinstance(text, str):
        raise MalformedRoomChoiceCommandError(f"expected a string command, got {text!r}")

    if text == _PLAY_COMMAND:
        return PlayCommand()

    if text == _CREATE_ROOM_COMMAND:
        return CreateRoomCommand()

    if text.startswith(_JOIN_ROOM_PREFIX):
        code = text[len(_JOIN_ROOM_PREFIX) :]
        if not code:
            raise MalformedRoomChoiceCommandError(f"code must not be empty in {text!r}")
        return JoinRoomCommand(code=code)

    raise MalformedRoomChoiceCommandError(
        f"expected 'PLAY', 'CREATE_ROOM', or 'JOIN_ROOM:<code>', got {text!r}"
    )
