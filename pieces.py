"""
Piece movement shape rules.

Each rule function takes (dr, dc, color, is_capture, is_start_row) where:
- dr, dc       = to_row - from_row, to_col - from_col
- color        = the moving piece's color, "w" or "b"
- is_capture   = True if the destination cell holds an enemy piece
- is_start_row = True if the piece is moving from its color's pawn
                 start row (only meaningful for pawns; ignored otherwise)

Most pieces only care about (dr, dc). Pawn is the exception: its
legality also depends on color (movement direction), whether the move
is a capture (straight = non-capture only, diagonal = capture only),
and whether a 2-cell opening move is allowed (only from the start row).

Obstruction ("blocked path") checks are handled separately in game.py.
"""


def _is_king_move(dr, dc, color, is_capture, is_start_row):
    if dr == 0 and dc == 0:
        return False
    return abs(dr) <= 1 and abs(dc) <= 1


def _is_rook_move(dr, dc, color, is_capture, is_start_row):
    if dr == 0 and dc == 0:
        return False
    return dr == 0 or dc == 0


def _is_bishop_move(dr, dc, color, is_capture, is_start_row):
    if dr == 0 and dc == 0:
        return False
    return abs(dr) == abs(dc)


def _is_queen_move(dr, dc, color, is_capture, is_start_row):
    return (
        _is_rook_move(dr, dc, color, is_capture, is_start_row)
        or _is_bishop_move(dr, dc, color, is_capture, is_start_row)
    )


def _is_knight_move(dr, dc, color, is_capture, is_start_row):
    return (abs(dr), abs(dc)) in ((1, 2), (2, 1))


def _is_pawn_move(dr, dc, color, is_capture, is_start_row):
    # White moves "upward" (decreasing row), black moves "downward"
    # (increasing row).
    forward = -1 if color == "w" else 1

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


# Maps the piece-letter (second char of a token, e.g. "wK" -> "K") to its
# shape-validation function.
MOVE_RULES = {
    "K": _is_king_move,
    "Q": _is_queen_move,
    "R": _is_rook_move,
    "B": _is_bishop_move,
    "N": _is_knight_move,
    "P": _is_pawn_move,
}


# Piece letters that slide along a straight line/diagonal and therefore
# must check for blockers along the path. Knight and King are excluded
# (knight jumps, king only moves one cell). Pawn is handled separately
# in game.py, only for its 2-cell opening move.
SLIDING_PIECES = {"R", "B", "Q"}


def path_cells(from_row, from_col, to_row, to_col):
    """
    Return the list of (row, col) cells strictly between the origin and
    destination (both exclusive), assuming a straight or diagonal line.
    """
    dr = to_row - from_row
    dc = to_col - from_col

    step_r = (dr > 0) - (dr < 0)   # -1, 0, or 1
    step_c = (dc > 0) - (dc < 0)   # -1, 0, or 1

    cells = []
    row, col = from_row + step_r, from_col + step_c
    while (row, col) != (to_row, to_col):
        cells.append((row, col))
        row += step_r
        col += step_c
    return cells


def is_legal_move(piece_letter, from_row, from_col, to_row, to_col, color, is_capture, is_start_row=False):
    rule = MOVE_RULES.get(piece_letter)
    if rule is None:
        # Unknown/unsupported piece type: no legal moves defined yet.
        return False
    dr = to_row - from_row
    dc = to_col - from_col
    return rule(dr, dc, color, is_capture, is_start_row)