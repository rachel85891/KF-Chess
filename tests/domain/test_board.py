import pytest

from kungfu_chess.domain.board import Board, ListBoardStorage
from kungfu_chess.domain.color import Color
from kungfu_chess.domain.piece import Piece, PieceType


def _always_legal(dr, dc, color, is_capture, is_start_row):
    return True


def _never_needs_path_check(dr, dc):
    return False


def _make_piece(letter="P", color=Color.WHITE):
    return Piece(
        color=color,
        piece_type=PieceType(letter=letter, name=letter, movement_rule=_always_legal, requires_clear_path=_never_needs_path_check),
    )


def test_from_grid_reports_dimensions():
    board = Board.from_grid([[None, None], [None, None], [None, None]])
    assert board.num_rows == 3
    assert board.num_cols == 2


def test_get_set_piece_round_trip():
    board = Board.from_grid([[None, None], [None, None]])
    piece = _make_piece()

    assert board.get_piece(0, 0) is None
    board.set_piece(0, 0, piece)
    assert board.get_piece(0, 0) is piece


def test_in_bounds():
    board = Board.from_grid([[None, None], [None, None]])
    assert board.in_bounds(0, 0) is True
    assert board.in_bounds(1, 1) is True
    assert board.in_bounds(2, 0) is False
    assert board.in_bounds(0, -1) is False


def test_iter_cells_yields_every_cell_with_coordinates():
    piece = _make_piece()
    board = Board.from_grid([[piece, None], [None, piece]])

    cells = list(board.iter_cells())

    assert cells == [
        (0, 0, piece),
        (0, 1, None),
        (1, 0, None),
        (1, 1, piece),
    ]


def test_board_delegates_to_injected_storage_bridge():
    """Board must not know or care which BoardStorage implementation it
    wraps - this is the seam a future binary storage plugs into."""

    class RecordingStorage(ListBoardStorage):
        def __init__(self, grid):
            super().__init__(grid)
            self.get_calls = []

        def get(self, row, col):
            self.get_calls.append((row, col))
            return super().get(row, col)

    storage = RecordingStorage([[None]])
    board = Board(storage)
    board.get_piece(0, 0)

    assert storage.get_calls == [(0, 0)]


def test_empty_grid_has_zero_columns():
    board = Board.from_grid([])
    assert board.num_rows == 0
    assert board.num_cols == 0
