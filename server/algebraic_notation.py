"""algebraic_notation.py: pure, standalone conversion between standard
chess algebraic notation squares ("e2") and this project's own
Position(row, col) coordinate (kungfu_chess/model/position.py) -
Stage B3 of the server track.

SRP: this module does exactly one thing - convert a two-character
square string to a Position (or raise a clear error for an invalid
one). It has no knowledge of the move-command grammar that wraps a
square ("WQe2e5"), no knowledge of networking, and no knowledge of
GameSession - see server/move_command.py for the layer that composes
this into a full command, and server/game_server.py for the layer that
actually calls request_move with the result.

ROW/COL MAPPING - re-derived, not assumed: files a-h map directly to
columns 0-7 (col = ord(file) - ord('a')). Ranks are the non-obvious
part, because this project's own Position(row, col) convention is
NOT "row 0 = rank 1" - it had to be re-derived from two already-
established facts in this codebase (re-checked directly before writing
this, not assumed):
  - server/game_session.py's STANDARD_STARTING_POSITION_LINES puts
    White's back rank on row 7 and Black's on row 0.
  - kungfu_chess/rules/piece_rules.py's _pawn_start_row puts White's
    pawns on row (board.height - 2) = row 6, Black's on row 1.
Standard algebraic notation puts White's back rank on rank 1 and pawns
on rank 2; Black's back rank on rank 8 and pawns on rank 7. Matching
row 7 <-> rank 1 and row 0 <-> rank 8 gives row = BOARD_SIZE - rank,
which was then cross-checked against BOTH facts above before being
trusted (see this module's own tests: e1/e8 against the two back
ranks, e2/e7 against the two pawn rows, all four independently
consistent with row = 8 - rank).

BOARD_SIZE = 8 is hardcoded, not derived from any real Board instance:
algebraic notation (files a-h, ranks 1-8) is only meaningful for a
standard 8x8 board in the first place - this module has, and needs, no
Board reference at all, staying a pure, dependency-free converter. A
future stage supporting non-standard board sizes would need its own,
separate notation scheme entirely; out of scope here (YAGNI).
"""

from __future__ import annotations

from kungfu_chess.model.position import Position

BOARD_SIZE = 8
_FILE_LETTERS = "abcdefgh"
_RANK_DIGITS = "12345678"


class InvalidSquareError(ValueError):
    """Raised by algebraic_to_position for any square string that
    isn't a valid two-character <file><rank> pair on an 8x8 board."""


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
