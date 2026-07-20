"""algebraic_notation.py: pure, standalone, BIDIRECTIONAL conversion
between standard chess algebraic notation squares ("e2") and this
project's own Position(row, col) coordinate
(kungfu_chess/model/position.py).

WHY THIS LIVES HERE, IN kungfu_chess/, NOT server/ (Stage B5
relocation): this logic was originally written at
server/algebraic_notation.py (Stage B3), one-directional
(square->Position only), for server/move_command.py's own incoming-
command parsing. Stage B5 needs the CLIENT to build outgoing move
commands too - and a client must never import from server/ (server
depends on kungfu_chess/, never the reverse - docs/spec.md §4's
existing, load-bearing dependency list: "Nothing ever points from
Model to UI!", of which "nothing client-side points into server/" is
the server-track's own direct extension). This module is therefore
the single shared home for this logic, importable by both server/ (a
thin re-export shim now lives at the old server/algebraic_notation.py
path - see that file's own docstring) and
kungfu_chess/client/network/ (this stage's new NetworkGameClient).
Nothing about the conversion logic itself changed in this move - see
this module's own tests, plus the pre-existing
tests/unit/server/test_algebraic_notation.py, which still passes
unmodified through the shim.

SRP: this module does exactly one thing (now in both directions) -
convert between a two-character square string and a Position, raising
a clear error for an invalid value on either side. It still has no
knowledge of the move-command grammar that wraps a square ("WQe2e5")
- see kungfu_chess/notation/move_command_format.py (the new, shared
formatter) and server/move_command.py (the existing parser) for the
layer that composes this into a full command.

ROW/COL MAPPING - unchanged from the original Stage B3 module (fully
re-verified, not just carried over blindly): files a-h map directly to
columns 0-7 (col = ord(file) - ord('a')). Ranks map via row = BOARD_SIZE
- rank, because this project's own Position(row, col) convention puts
White's back rank on row 7 and Black's on row 0 (server/game_session.py's
STANDARD_STARTING_POSITION_LINES), with White's pawns on row
board.height - 2 = row 6 and Black's on row 1
(kungfu_chess/rules/piece_rules.py's _pawn_start_row) - matching
standard algebraic notation's rank 1 (White back rank) <-> row 7 and
rank 8 (Black back rank) <-> row 0.

BOARD_SIZE = 8 is hardcoded, not derived from any real Board instance:
algebraic notation (files a-h, ranks 1-8) is only meaningful for a
standard 8x8 board in the first place - this module has, and needs, no
Board reference at all, staying a pure, dependency-free converter. A
future stage supporting non-standard board sizes would need its own,
separate notation scheme entirely; out of scope here (YAGNI).

NEW IN STAGE B5 - position_to_algebraic, the reverse direction: needed
because a CLIENT must BUILD outgoing move commands from a Position (a
piece the player clicked/selected), not just parse incoming ones - the
exact opposite need server/move_command.py's parser has always had.
Raises the new InvalidPositionError for any Position outside the valid
0-7/0-7 range on either axis - symmetric with algebraic_to_position's
own InvalidSquareError for the opposite direction, so a caller of
either function gets an equally clear, equally named-for-its-direction
error rather than a bare, unexplained KeyError/IndexError.
"""

from __future__ import annotations

from kungfu_chess.model.position import Position

BOARD_SIZE = 8
_FILE_LETTERS = "abcdefgh"
_RANK_DIGITS = "12345678"


class InvalidSquareError(ValueError):
    """Raised by algebraic_to_position for any square string that
    isn't a valid two-character <file><rank> pair on an 8x8 board."""


class InvalidPositionError(ValueError):
    """Raised by position_to_algebraic for any Position whose row or
    col falls outside 0-7 - the reverse-direction counterpart of
    InvalidSquareError."""


def algebraic_to_position(square: str) -> Position:
    """Convert a standard algebraic notation square (e.g. "e2") to a
    Position, per this module's own "ROW/COL MAPPING" docstring
    section.

    Args:
        square: A two-character square string - file letter (a-h,
            case-insensitive) followed by rank digit (1-8).

    Returns:
        The corresponding Position.

    Raises:
        InvalidSquareError: If `square` is not exactly 2 characters, or
            its file/rank is out of the a-h / 1-8 range.
    """

    if len(square) != 2:
        raise InvalidSquareError(f"expected a 2-character square like 'e2', got {square!r}")

    file_letter, rank_digit = square[0].lower(), square[1]

    if file_letter not in _FILE_LETTERS:
        raise InvalidSquareError(f"invalid file {square[0]!r} in square {square!r} (expected 'a'-'h')")
    if rank_digit not in _RANK_DIGITS:
        raise InvalidSquareError(f"invalid rank {rank_digit!r} in square {square!r} (expected '1'-'8')")

    col = _FILE_LETTERS.index(file_letter)
    rank = int(rank_digit)
    row = BOARD_SIZE - rank
    return Position(row=row, col=col)


def position_to_algebraic(position: Position) -> str:
    """Convert a Position to its standard algebraic notation square
    (e.g. Position(row=6, col=4) -> "e2") - the exact inverse of
    algebraic_to_position, per this module's own "ROW/COL MAPPING"
    section (rank = BOARD_SIZE - row).

    Args:
        position: The Position to convert.

    Returns:
        The corresponding two-character square string, lowercase file
            letter followed by rank digit.

    Raises:
        InvalidPositionError: If position.row or position.col falls
            outside 0-7.
    """

    if not (0 <= position.row < BOARD_SIZE):
        raise InvalidPositionError(f"row {position.row} is outside the 8x8 board (expected 0-7): {position!r}")
    if not (0 <= position.col < BOARD_SIZE):
        raise InvalidPositionError(f"col {position.col} is outside the 8x8 board (expected 0-7): {position!r}")

    file_letter = _FILE_LETTERS[position.col]
    rank = BOARD_SIZE - position.row
    return f"{file_letter}{rank}"
