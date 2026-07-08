from kungfu_chess.config.piece_registry import PieceTypeRegistry
from kungfu_chess.domain.board import Board
from kungfu_chess.domain.color import Color
from kungfu_chess.domain.piece import Piece
from kungfu_chess.services.move_legality_service import is_move_allowed

REGISTRY = PieceTypeRegistry.standard_chess()


def _piece(letter, color):
    return Piece(color=color, piece_type=REGISTRY.get(letter))


def test_same_color_capture_is_blocked():
    board = Board.from_grid([
        [_piece("R", Color.WHITE), _piece("P", Color.WHITE)],
    ])
    assert is_move_allowed(board, (0, 0), (0, 1)) is False


def test_shape_illegal_move_is_blocked():
    board = Board.from_grid([
        [_piece("N", Color.WHITE), None, None],
        [None, None, None],
    ])
    # knight cannot move one cell straight
    assert is_move_allowed(board, (0, 0), (0, 1)) is False


def test_sliding_piece_blocked_by_intervening_piece():
    board = Board.from_grid([
        [_piece("R", Color.WHITE), _piece("P", Color.WHITE), None],
    ])
    assert is_move_allowed(board, (0, 0), (0, 2)) is False


def test_step_piece_never_needs_clear_path():
    board = Board.from_grid([
        [_piece("K", Color.WHITE), None],
        [None, None],
    ])
    assert is_move_allowed(board, (0, 0), (1, 1)) is True


def test_empty_origin_is_not_a_legal_move_source():
    board = Board.from_grid([[None, None]])
    assert is_move_allowed(board, (0, 0), (0, 1)) is False


def test_pawn_double_step_legal_exactly_from_board_edge_start_row():
    """White pawns start on the board's LAST row, black on row 0 - not
    the standard one-row-in chess convention. This is the highest-risk
    behavior in the whole migration; do not "correct" it."""
    board = Board.from_grid([
        [None],
        [None],
        [_piece("P", Color.WHITE)],
    ])
    assert is_move_allowed(board, (2, 0), (0, 0)) is True




def test_pawn_double_step_rejected_when_not_on_start_row():
    board = Board.from_grid([
        [None],
        [None],
        [_piece("P", Color.WHITE)],
        [None],
    ])
    # start row is row 3 (num_rows-1); this pawn sits on row 2, not the start row
    assert is_move_allowed(board, (2, 0), (0, 0)) is False


def test_black_pawn_start_row_is_row_zero():
    board = Board.from_grid([
        [_piece("P", Color.BLACK)],
        [None],
        [None],
    ])
    assert is_move_allowed(board, (0, 0), (2, 0)) is True
