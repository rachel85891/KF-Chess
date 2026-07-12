"""Piece movement geometry: shape rules and straight/diagonal line
cells, as plain functions - no piece-letter strings anywhere in this
module, only geometry/color/capture logic. Relocated here from the
retired domain/movement/{rules,path}.py (merged into one file - both
had exactly one consumer, rules/piece_rules.py, so keeping them split
across two files no longer served a purpose): this is the natural
completion of the PieceRules step's original reuse decision, not a new
dependency.

Each is_*_move function takes (dr, dc, color, is_capture, is_start_row)
where:
- dr, dc       = to_row - from_row, to_col - from_col
- color        = the moving piece's color
- is_capture   = True if the destination cell holds an enemy piece
- is_start_row = True if the piece is moving from its color's pawn
                 start row (only meaningful for pawns; ignored otherwise)

path_cells returns the cells strictly between origin and destination
(both exclusive), assuming a straight or diagonal line between them.
"""

from __future__ import annotations

from typing import Tuple

from kungfu_chess.model.color import Color

Cell = Tuple[int, int]


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


def path_cells(from_row: int, from_col: int, to_row: int, to_col: int) -> list[Cell]:
    dr = to_row - from_row
    dc = to_col - from_col

    step_r = (dr > 0) - (dr < 0)
    step_c = (dc > 0) - (dc < 0)

    cells: list[Cell] = []
    row, col = from_row + step_r, from_col + step_c
    while (row, col) != (to_row, to_col):
        cells.append((row, col))
        row += step_r
        col += step_c
    return cells
