from __future__ import annotations

from kungfu_chess.domain.color import Color
from kungfu_chess.model.board import Board
from kungfu_chess.model.piece import Piece, PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.rules.rule_engine import RuleEngine


def _empty_grid(rows: int, cols: int) -> list[list[None]]:
    return [[None for _ in range(cols)] for _ in range(rows)]


def _piece(color: Color, kind: PieceKind, cell: Position) -> Piece:
    return Piece(color=color, kind=kind, cell=cell)


def test_move_with_out_of_bounds_source_is_rejected():
    board = Board(_empty_grid(3, 3))

    result = RuleEngine().validate_move(board, Position(row=5, col=5), Position(row=0, col=0))

    assert result.is_valid is False
    assert result.reason == "outside_board"


def test_move_with_out_of_bounds_destination_is_rejected():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)

    result = RuleEngine().validate_move(board, Position(row=0, col=0), Position(row=5, col=5))

    assert result.is_valid is False
    assert result.reason == "outside_board"


def test_move_from_empty_cell_is_rejected():
    board = Board(_empty_grid(3, 3))

    result = RuleEngine().validate_move(board, Position(row=0, col=0), Position(row=1, col=1))

    assert result.is_valid is False
    assert result.reason == "empty_source"


def test_move_onto_friendly_piece_is_rejected():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    friendly = _piece(Color.WHITE, PieceKind.PAWN, Position(row=0, col=1))
    grid[0][0] = rook
    grid[0][1] = friendly
    board = Board(grid)

    result = RuleEngine().validate_move(board, Position(row=0, col=0), Position(row=0, col=1))

    assert result.is_valid is False
    assert result.reason == "friendly_destination"


def test_move_that_violates_piece_shape_is_rejected():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)

    result = RuleEngine().validate_move(board, Position(row=0, col=0), Position(row=1, col=1))

    assert result.is_valid is False
    assert result.reason == "illegal_piece_move"


def test_valid_move_is_accepted():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)

    result = RuleEngine().validate_move(board, Position(row=0, col=0), Position(row=0, col=2))

    assert result.is_valid is True
    assert result.reason == "ok"


def test_rook_move_blocked_by_intervening_piece_is_rejected():
    grid = _empty_grid(4, 4)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    blocker = _piece(Color.WHITE, PieceKind.PAWN, Position(row=0, col=1))
    grid[0][0] = rook
    grid[0][1] = blocker
    board = Board(grid)

    result = RuleEngine().validate_move(board, Position(row=0, col=0), Position(row=0, col=3))

    assert result.is_valid is False
    assert result.reason == "illegal_piece_move"


def test_rook_captures_enemy_blocker_is_accepted():
    grid = _empty_grid(4, 4)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    enemy = _piece(Color.BLACK, PieceKind.PAWN, Position(row=0, col=2))
    grid[0][0] = rook
    grid[0][2] = enemy
    board = Board(grid)

    result = RuleEngine().validate_move(board, Position(row=0, col=0), Position(row=0, col=2))

    assert result.is_valid is True
    assert result.reason == "ok"
