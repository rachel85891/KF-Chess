"""game_event_wire_format.py: bidirectional conversion between real
client-layer events (kungfu_chess.client.events.game_events -
MoveAccepted, JumpAccepted, PieceArrived) and a simple, single-line,
human-readable wire text format - Stage B7 of the server track.

WHY A NEW MODULE, NOT REUSING move_command_format.py: that module
formats an OUTGOING move REQUEST (client -> server, "WQe2e5" - no
piece_id/duration, since the server hasn't accepted anything yet).
This module formats CONFIRMED GAME EVENTS (server -> client) that
already carry piece_id/duration_ms/captured_piece_id - a materially
different shape and direction of data, not a variant of the same
grammar. Both DO share the same underlying square<->Position
conversion (position_to_algebraic/algebraic_to_position from
kungfu_chess.notation.algebraic_notation) - reused here directly, not
re-derived, per this project's own DRY convention already established
between move_command_format.py and server/move_command.py.

WHY A DISTINCT SINGLE-LINE PREFIX ("EVT:"), NOT JSON: this project's
existing wire conventions (server/game_server.py's own
"assigned_color:white"/"server_full", move_command_format.py's
"WQe2e5") are all plain, single-line, colon/prefix-delimited text, not
JSON - this module continues that convention rather than introducing a
second wire-format style for one message type. The existing board-text
snapshot broadcast (BoardPrinter's format) is the only OTHER message
shape a client ever receives, and it always spans board.height LINES
(never one) - a single line beginning with "EVT:" can therefore never
be produced by BoardPrinter (board notation tokens are 1-2 characters
with no colons) and can never be mistaken for one, giving a caller a
trivial, unambiguous `text.startswith(EVENT_MESSAGE_PREFIX)` dispatch
with no risk of misparsing one format as the other.

ONE ERROR TYPE for every malformed/unrecognized reason
(MalformedGameEventWireFormatError) - mirrors server/move_command.py's
own "ONE ERROR TYPE" convention exactly: a caller (NetworkGameLoopRunner)
only ever needs to catch this one type to know "ignore this message",
regardless of which specific part was wrong.

captured_piece_id's "none" token (not an empty string): PieceArrived's
captured_piece_id is Optional[int], and a literal 0 is a valid real id
(the process-global counter in kungfu_chess/model/piece.py starts at
0) - an empty-string convention would be ambiguous with "the field is
missing" in a way indistinguishable from a real, valid id, so "none" is
a distinct, explicit third token that can never collide with a
decimal integer's own string form.

SRP: this module ONLY converts between real event dataclasses and text
- no networking, no rendering, no animation-timing, and (unlike
server/game_server.py's own broadcaster) no piece_id TRANSLATION
either. See kungfu_chess/client/loop/network_game_loop_runner.py's own
docstring for why the raw piece_id carried over the wire cannot be fed
directly into a client-side PieceAnimatorRegistry unchanged (process-
local id spaces don't match across the two processes) - that
translation is a client-side concern, deliberately kept OUT of this
pure, bidirectional format module, which only ever sees the numbers
it's given and passes them through unchanged in both directions.
"""

from __future__ import annotations

from typing import Optional

from kungfu_chess.client.events.game_events import JumpAccepted, MoveAccepted, PieceArrived
from kungfu_chess.notation.algebraic_notation import algebraic_to_position, position_to_algebraic

EVENT_MESSAGE_PREFIX = "EVT:"

_MESSAGE_MARKER = "EVT"
_MOVE_TAG = "MOVE"
_JUMP_TAG = "JUMP"
_ARRIVED_TAG = "ARRIVED"
_NONE_TOKEN = "none"
_FIELD_SEP = ":"

# Total ":"-separated fields, INCLUDING the leading "EVT" marker and the
# tag itself (both are their own fields, not part of one combined
# "EVT:MOVE" token - splitting the whole message on the same ":" used
# between every other field means the marker/tag must be split
# consistently with everything else, not concatenated with a colon
# beforehand and then re-split, which would corrupt the tag).
_MOVE_LIKE_FIELD_COUNT = 6  # EVT, tag, piece_id, from, to, duration_ms
_ARRIVED_FIELD_COUNT = 5  # EVT, tag, piece_id, cell, captured_piece_id


class GameEventWireFormatError(ValueError):
    """Base class for this module's own errors - mirrors
    server/move_command.py's ValueError-subclassing convention
    (algebraic_notation.py's own InvalidSquareError/
    InvalidPositionError are also plain ValueErrors)."""


class MalformedGameEventWireFormatError(GameEventWireFormatError):
    """Raised by parse_game_event for any text that isn't a valid wire
    message in this module's format - see module docstring's "ONE
    ERROR TYPE" section."""


def format_game_event(event: object) -> Optional[str]:
    """Format a real client-layer event as wire text, or return None if
    `event` isn't one of the three motion-related types this module
    knows about.

    Args:
        event: Any published client-layer event object.

    Returns:
        The wire text, or None if `event` is not a MoveAccepted,
        JumpAccepted, or PieceArrived (e.g. MoveRejected/GameOver/
        PromotionEvent/MoveRequested - none of these are animatable
        motions, so callers like server/game_server.py's own
        broadcaster use this None to know not to send anything extra
        for them).

    Raises:
        InvalidPositionError: Propagated from position_to_algebraic if
            any Position on `event` falls outside the 8x8 board -
            believed unreachable in practice, since every event this
            module ever receives originates from a real Board/
            GameEngine, whose Positions are already board-legal.
    """

    if isinstance(event, (MoveAccepted, JumpAccepted)):
        tag = _MOVE_TAG if isinstance(event, MoveAccepted) else _JUMP_TAG
        return _FIELD_SEP.join(
            [
                _MESSAGE_MARKER,
                tag,
                str(event.piece_id),
                position_to_algebraic(event.from_cell),
                position_to_algebraic(event.to_cell),
                str(event.duration_ms),
            ]
        )

    if isinstance(event, PieceArrived):
        captured_token = _NONE_TOKEN if event.captured_piece_id is None else str(event.captured_piece_id)
        return _FIELD_SEP.join(
            [_MESSAGE_MARKER, _ARRIVED_TAG, str(event.piece_id), position_to_algebraic(event.cell), captured_token]
        )

    return None


def parse_game_event(text: str) -> object:
    """Parse one raw wire message back into a real MoveAccepted,
    JumpAccepted, or PieceArrived - the exact inverse of
    format_game_event.

    Args:
        text: The raw message text - a caller should already know this
            starts with EVENT_MESSAGE_PREFIX (see module docstring's
            "WHY A DISTINCT SINGLE-LINE PREFIX" section) via a plain
            `text.startswith(EVENT_MESSAGE_PREFIX)` dispatch before
            ever calling this function; guarded here too regardless.

    Returns:
        A real MoveAccepted, JumpAccepted, or PieceArrived instance,
        equal in every field to whatever format_game_event was
        originally given.

    Raises:
        MalformedGameEventWireFormatError: If `text` doesn't start
            with EVENT_MESSAGE_PREFIX, has the wrong number of fields
            for its own tag, names an unrecognized tag, or has a
            non-integer piece_id/duration_ms/captured_piece_id or an
            invalid algebraic square.
    """

    fields = text.split(_FIELD_SEP)
    if len(fields) < 2 or fields[0] != _MESSAGE_MARKER:
        raise MalformedGameEventWireFormatError(f"not a game-event wire message: {text!r}")

    tag = fields[1]

    try:
        if tag in (_MOVE_TAG, _JUMP_TAG):
            if len(fields) != _MOVE_LIKE_FIELD_COUNT:
                raise MalformedGameEventWireFormatError(
                    f"expected {_MOVE_LIKE_FIELD_COUNT} fields for {tag}, got {len(fields)}: {text!r}"
                )
            piece_id = int(fields[2])
            from_cell = algebraic_to_position(fields[3])
            to_cell = algebraic_to_position(fields[4])
            duration_ms = int(fields[5])
            event_cls = MoveAccepted if tag == _MOVE_TAG else JumpAccepted
            return event_cls(piece_id=piece_id, from_cell=from_cell, to_cell=to_cell, duration_ms=duration_ms)

        if tag == _ARRIVED_TAG:
            if len(fields) != _ARRIVED_FIELD_COUNT:
                raise MalformedGameEventWireFormatError(
                    f"expected {_ARRIVED_FIELD_COUNT} fields for {tag}, got {len(fields)}: {text!r}"
                )
            piece_id = int(fields[2])
            cell = algebraic_to_position(fields[3])
            captured_token = fields[4]
            captured_piece_id = None if captured_token == _NONE_TOKEN else int(captured_token)
            return PieceArrived(piece_id=piece_id, cell=cell, captured_piece_id=captured_piece_id)
    except MalformedGameEventWireFormatError:
        raise
    except ValueError as exc:
        raise MalformedGameEventWireFormatError(f"malformed field in {text!r}: {exc}") from None

    raise MalformedGameEventWireFormatError(f"unrecognized game-event tag {tag!r} in {text!r}")
