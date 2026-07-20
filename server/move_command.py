"""move_command.py: parses the real WS move-command grammar this
server understands - "<W|B><K|Q|R|B|N|P><file><rank><file><rank>", e.g.
"WQe2e5" (the CTD26 slides' own documented format: mover's color,
moving piece's kind letter, source square, destination square) - into
a structured ParsedMoveCommand.

SRP, and why this is its own module, not inlined in the WS handler:
this is a pure parser with no networking/GameSession/ConnectionManager
knowledge - independently unit-testable on its own (per this stage's
own requirement), exactly like kungfu_chess/notation/algebraic_notation.py
(which it depends on for the two square conversions) stays independent
of this module in turn.

STAGE B5 UPDATE: the square<->Position conversion this module depends
on now lives at kungfu_chess/notation/algebraic_notation.py, not
server/algebraic_notation.py - relocated so a client (which must never
import from server/) can share the exact same logic to build outgoing
commands. server/algebraic_notation.py still exists, as a thin
re-export shim, purely for backward-compatible imports (see its own
docstring) - this module now imports from the new location directly.

WHY the piece-kind letter is parsed here but NOT validated against a
real board here: per this project's own established convention, the
actual move is driven by the two coordinates alone (Position, not a
piece-kind parameter) - every existing client->engine path already
works this way (Controller.click -> GameEngine.request_move(from, to),
GameEventPublisher.request_move(from, to); none of them take a piece
kind at all). The piece letter is informational per the wire format,
and re-validated against what's ACTUALLY on the source square before
being acted on - but that check needs a real Board to compare against,
which this module deliberately has no reference to (it is pure,
board-agnostic parsing). That validation therefore lives in
server/game_server.py, the one component that already holds both a
parsed command and a real GameSession/board to check it against - see
GameServer._handle_message's own docstring for that check.

ONE ERROR TYPE for every malformed reason: MalformedCommandError is
raised for a wrong length, an unknown color letter, an unknown piece
letter, OR an invalid square (this module catches
algebraic_notation.InvalidSquareError - itself a plain ValueError - and
re-wraps it) - a caller (GameServer) only ever needs to catch this one
exception type to know "reject this client's message", regardless of
which specific part of the 6 characters was wrong. This mirrors
kungfu_chess/io/board_parser.py's own single-error-per-.parse()-call
contract (one clear signal that something in the input was invalid),
rather than needing per-field exception handling at the call site.
"""

from __future__ import annotations

from dataclasses import dataclass

from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.notation.algebraic_notation import algebraic_to_position

_COMMAND_LENGTH = 6


class MalformedCommandError(ValueError):
    """Raised by parse_move_command for any input that isn't a valid
    6-character move command - see module docstring's "ONE ERROR TYPE"
    section."""


@dataclass(frozen=True)
class ParsedMoveCommand:
    """The structured result of successfully parsing one move command
    - a plain data holder, per this project's own game_events.py-style
    convention for event/result shapes (frozen, no behavior)."""

    color: Color
    piece_kind: PieceKind
    from_cell: Position
    to_cell: Position


def parse_move_command(text: str) -> ParsedMoveCommand:
    """Parse one raw move-command string into a ParsedMoveCommand.

    Args:
        text: The raw text received from a client, expected to be
            exactly 6 characters: "<W|B><K|Q|R|B|N|P><file><rank>
            <file><rank>", e.g. "WQe2e5".

    Returns:
        The parsed command.

    Raises:
        MalformedCommandError: If `text` is not exactly 6 characters,
            its color letter isn't 'W'/'B', its piece letter isn't one
            of K/Q/R/B/N/P, or either square is invalid (see module
            docstring's "ONE ERROR TYPE" section) - all case-
            insensitive.
    """

    if len(text) != _COMMAND_LENGTH:
        raise MalformedCommandError(f"expected a {_COMMAND_LENGTH}-character command like 'WQe2e5', got {text!r}")

    color_letter, kind_letter, from_square, to_square = text[0], text[1], text[2:4], text[4:6]

    try:
        color = Color(color_letter.lower())
    except ValueError:
        raise MalformedCommandError(f"unknown color letter {color_letter!r} in {text!r} (expected 'W' or 'B')") from None

    try:
        piece_kind = PieceKind(kind_letter.upper())
    except ValueError:
        raise MalformedCommandError(
            f"unknown piece letter {kind_letter!r} in {text!r} (expected one of K/Q/R/B/N/P)"
        ) from None

    try:
        from_cell = algebraic_to_position(from_square)
        to_cell = algebraic_to_position(to_square)
    except ValueError as exc:
        raise MalformedCommandError(f"invalid square in command {text!r}: {exc}") from None

    return ParsedMoveCommand(color=color, piece_kind=piece_kind, from_cell=from_cell, to_cell=to_cell)
