"""jump_command.py: parses the real WS jump-command grammar this
server understands - "J<W|B><K|Q|R|B|N|P><file><rank>", e.g. "JWRe2"
(the jumping piece's own current cell - not a from/to pair) - into a
structured ParsedJumpCommand.

WHY THIS EXISTS, AND WHY ITS SHAPE DIFFERS FROM A MOVE COMMAND:
ExtraEngine.request_jump(cell) (kungfu_chess/extra/extra_engine.py,
re-read directly before writing this) takes ONLY the piece's own
current cell - `self.engine.board.piece_at(cell)` is looked up
internally - never a from/to pair the way GameEngine.request_move
does. A jump command therefore only ever needs to carry ONE square,
plus color/piece-kind (informational, validated against the board the
same way move_command.py's own piece letter is - see that module's own
docstring for why the check itself lives in server/game_server.py, not
here): "J" + color + piece + one square = 5 characters, vs. a move
command's fixed 6.

WHY THIS LIVES IN kungfu_chess/notation/, NOT server/ (unlike
server/move_command.py's own placement): this is a pure, board-
agnostic parser - exactly like algebraic_notation.py already is in
this same package - with no GameSession/ConnectionManager knowledge at
all. Since server/ depends on kungfu_chess/, never the reverse (see
algebraic_notation.py's own docstring for the full "server depends on
kungfu_chess/" reasoning), placing a pure parser here is architecturally
cleaner than server/move_command.py's own historical placement (Stage
B3, before this notation package existed) - not a deviation this module
needs to defend, just the more natural home for a brand new module with
no networking dependency of its own. server/game_server.py imports this
module directly, the same direction it already imports
kungfu_chess/notation/game_event_wire_format.py from.

WIRE FORMAT / DISAMBIGUATION FROM A MOVE COMMAND: a leading "J" marker
character (JUMP_COMMAND_PREFIX) that can never appear as the first
character of a valid move command - server/move_command.py's own
grammar always starts with a bare color letter, 'W' or 'B'
(case-insensitive), never 'J'. server/game_server.py's own dispatch
(see that module's own docstring) checks this ONE leading character to
decide which parser a raw incoming message goes to - the same "distinct
leading marker, unambiguous by construction" principle
game_event_wire_format.py already uses for its own "EVT:" prefix,
preferred here over relying on length alone (5 vs. 6) precisely because
a leading marker is self-describing to a human reading raw wire
traffic, not just a fact a reader has to already know to notice. The
differing length (5 vs 6) is a second, entirely redundant confirmation
of the same distinction - not itself required for correctness.

ONE ERROR TYPE for every malformed reason (MalformedJumpCommandError) -
mirrors move_command.py's own "ONE ERROR TYPE" convention exactly: a
caller only ever needs to catch this one type to know "reject this
client's jump request", regardless of which specific part of the 5
characters was wrong.
"""

from __future__ import annotations

from dataclasses import dataclass

from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.notation.algebraic_notation import algebraic_to_position

JUMP_COMMAND_PREFIX = "J"
_COMMAND_LENGTH = 5  # "J" + color + piece + 2-char square


class MalformedJumpCommandError(ValueError):
    """Raised by parse_jump_command for any input that isn't a valid
    5-character jump command - see module docstring's "ONE ERROR TYPE"
    section."""


@dataclass(frozen=True)
class ParsedJumpCommand:
    """The structured result of successfully parsing one jump command
    - a plain data holder, matching ParsedMoveCommand's own convention
    (frozen, no behavior)."""

    color: Color
    piece_kind: PieceKind
    cell: Position


def parse_jump_command(text: str) -> ParsedJumpCommand:
    """Parse one raw jump-command string into a ParsedJumpCommand.

    Args:
        text: The raw text received from a client, expected to be
            exactly 5 characters: "J<W|B><K|Q|R|B|N|P><file><rank>",
            e.g. "JWRe2".

    Returns:
        The parsed command.

    Raises:
        MalformedJumpCommandError: If `text` is not exactly 5
            characters starting with JUMP_COMMAND_PREFIX, its color
            letter isn't 'W'/'B', its piece letter isn't one of
            K/Q/R/B/N/P, or the square is invalid (see module
            docstring's "ONE ERROR TYPE" section) - all case-
            insensitive, INCLUDING the leading "J" marker itself,
            matching move_command.py's own fully case-insensitive
            convention exactly (unlike game_event_wire_format.py's
            "EVT:" prefix, which is machine-generated only in both
            directions and therefore never needed a case-insensitive
            match).
    """

    if len(text) != _COMMAND_LENGTH or not text[:1].upper() == JUMP_COMMAND_PREFIX:
        raise MalformedJumpCommandError(
            f"expected a {_COMMAND_LENGTH}-character jump command like 'JWRe2' "
            f"starting with {JUMP_COMMAND_PREFIX!r}, got {text!r}"
        )

    color_letter, kind_letter, square = text[1], text[2], text[3:5]

    try:
        color = Color(color_letter.lower())
    except ValueError:
        raise MalformedJumpCommandError(f"unknown color letter {color_letter!r} in {text!r} (expected 'W' or 'B')") from None

    try:
        piece_kind = PieceKind(kind_letter.upper())
    except ValueError:
        raise MalformedJumpCommandError(
            f"unknown piece letter {kind_letter!r} in {text!r} (expected one of K/Q/R/B/N/P)"
        ) from None

    try:
        cell = algebraic_to_position(square)
    except ValueError as exc:
        raise MalformedJumpCommandError(f"invalid square in command {text!r}: {exc}") from None

    return ParsedJumpCommand(color=color, piece_kind=piece_kind, cell=cell)
