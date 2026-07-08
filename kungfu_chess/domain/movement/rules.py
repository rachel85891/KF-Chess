"""Piece movement shape rules, as plain functions - no piece-letter
strings anywhere in this module, only geometry/color/capture logic.
Which letter maps to which function is configuration data, assembled in
kungfu_chess.config.piece_registry, not something these functions know
about themselves.

Each function takes (dr, dc, color, is_capture, is_start_row) where:
- dr, dc       = to_row - from_row, to_col - from_col
- color        = the moving piece's color
- is_capture   = True if the destination cell holds an enemy piece
- is_start_row = True if the piece is moving from its color's pawn
                 start row (only meaningful for pawns; ignored otherwise)
"""

from kungfu_chess.domain.color import Color


def is_king_move(dr: int, dc: int, color: Color, is_capture: bool, is_start_row: bool) -> bool:
    if dr == 0 and dc == 0:
        return False
    return abs(dr) <= 1 and abs(dc) <= 1


def is_rook_move(dr: int, dc: int, color: Color, is_capture: bool, is_start_row: bool) -> bool:
    if dr == 0 and dc == 0:
        return False
    return dr == 0 or dc == 0


def is_bishop_move(dr: int, dc: int, color: Color, is_capture: bool, is_start_row: bool) -> bool:
    if dr == 0 and dc == 0:
        return False
    return abs(dr) == abs(dc)


def is_queen_move(dr: int, dc: int, color: Color, is_capture: bool, is_start_row: bool) -> bool:
    return (
        is_rook_move(dr, dc, color, is_capture, is_start_row)
        or is_bishop_move(dr, dc, color, is_capture, is_start_row)
    )


def is_knight_move(dr: int, dc: int, color: Color, is_capture: bool, is_start_row: bool) -> bool:
    return (abs(dr), abs(dc)) in ((1, 2), (2, 1))


def is_pawn_move(dr: int, dc: int, color: Color, is_capture: bool, is_start_row: bool) -> bool:
    # White moves "upward" (decreasing row), black moves "downward"
    # (increasing row).
    forward = -1 if color == Color.WHITE else 1

    if dc == 0:
        # Straight move: never a capture.
        if is_capture:
            return False
        if dr == forward:
            return True
        # 2-cell opening move: only from the pawn's start row.
        if is_start_row and dr == forward * 2:
            return True
        return False

    if abs(dc) == 1:
        # Diagonal move: exactly one step forward-diagonal, and must
        # be a capture (pawns cannot move diagonally without capturing).
        return dr == forward and is_capture

    return False
