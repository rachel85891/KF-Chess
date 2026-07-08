"""Move legality: same-color-capture guard + shape check + path-clear
check. This is the single source of truth for "is this move allowed
right now," reused unmodified both when a move is first requested and
again when it settles (the board may have changed in between).

Stateless module-level functions, not a class - there is no injected
collaborator here, just a pure query over a Board.
"""

from kungfu_chess.domain.board import Board
from kungfu_chess.domain.color import Color
from kungfu_chess.domain.movement.path import path_cells

Cell = tuple[int, int]


def _pawn_start_row(board: Board, color: Color) -> int:
    """The row a color's pawns begin on: white on the board's last row,
    black on row 0 (board-edge rows, not the standard "one row in"
    chess convention). Computed for every piece, not just pawns - only
    PawnRule actually reads the resulting is_start_row flag, every
    other MovementRule ignores it, so gating this on piece letter would
    just be a hardcoded string with no behavioral purpose."""
    if color == Color.WHITE:
        return board.num_rows - 1
    return 0


def is_move_allowed(board: Board, from_cell: Cell, to_cell: Cell) -> bool:
    from_row, from_col = from_cell
    to_row, to_col = to_cell

    piece = board.get_piece(from_row, from_col)
    if piece is None:
        return False

    destination = board.get_piece(to_row, to_col)
    if destination is not None and destination.color == piece.color:
        return False

    is_capture = destination is not None
    dr, dc = to_row - from_row, to_col - from_col
    is_start_row = from_row == _pawn_start_row(board, piece.color)

    piece_type = piece.piece_type
    if not piece_type.movement_rule(dr, dc, piece.color, is_capture, is_start_row):
        return False

    if piece_type.requires_clear_path(dr, dc):
        for row, col in path_cells(from_row, from_col, to_row, to_col):
            if board.get_piece(row, col) is not None:
                return False

    return True
