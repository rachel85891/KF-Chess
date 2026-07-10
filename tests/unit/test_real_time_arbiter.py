from __future__ import annotations

from kungfu_chess.domain.color import Color
from kungfu_chess.model.board import Board
from kungfu_chess.model.piece import Piece, PieceKind, PieceState
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter


def _empty_grid(rows: int, cols: int) -> list[list[None]]:
    return [[None for _ in range(cols)] for _ in range(rows)]


def _piece(color: Color, kind: PieceKind, cell: Position) -> Piece:
    return Piece(color=color, kind=kind, cell=cell)


def test_one_square_move_takes_1000ms():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(rook, Position(row=0, col=1), start_time=0)

    assert arbiter.advance_time(board, 999) == []
    assert board.piece_at(Position(row=0, col=1)) is None

    events = arbiter.advance_time(board, 1000)

    assert len(events) == 1
    assert board.piece_at(Position(row=0, col=1)) is rook


def test_n_square_move_takes_n_times_1000ms():
    grid = _empty_grid(3, 5)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(rook, Position(row=0, col=3), start_time=0)

    assert arbiter.advance_time(board, 2999) == []
    events = arbiter.advance_time(board, 3000)
    assert len(events) == 1
    assert board.piece_at(Position(row=0, col=3)) is rook


def test_diagonal_move_uses_chebyshev_distance_not_euclidean():
    grid = _empty_grid(5, 5)
    bishop = _piece(Color.WHITE, PieceKind.BISHOP, Position(row=0, col=0))
    grid[0][0] = bishop
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(bishop, Position(row=3, col=3), start_time=0)

    assert arbiter.advance_time(board, 2999) == []
    events = arbiter.advance_time(board, 3000)
    assert len(events) == 1
    assert board.piece_at(Position(row=3, col=3)) is bishop


def test_arrival_clears_source_and_occupies_destination():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(rook, Position(row=0, col=2), start_time=0)
    arbiter.advance_time(board, 2000)

    assert board.piece_at(Position(row=0, col=0)) is None
    assert board.piece_at(Position(row=0, col=2)) is rook


def test_arrival_captures_occupying_piece():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    enemy = _piece(Color.BLACK, PieceKind.PAWN, Position(row=0, col=1))
    grid[0][0] = rook
    grid[0][1] = enemy
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(rook, Position(row=0, col=1), start_time=0)
    events = arbiter.advance_time(board, 1000)

    assert board.piece_at(Position(row=0, col=1)) is rook
    assert events[0].captured_piece is enemy


def test_arrival_capturing_king_flags_king_captured():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    king = _piece(Color.BLACK, PieceKind.KING, Position(row=0, col=1))
    grid[0][0] = rook
    grid[0][1] = king
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(rook, Position(row=0, col=1), start_time=0)
    events = arbiter.advance_time(board, 1000)

    assert events[0].king_captured is True


def test_arrival_capturing_non_king_does_not_flag_king_captured():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    enemy = _piece(Color.BLACK, PieceKind.PAWN, Position(row=0, col=1))
    grid[0][0] = rook
    grid[0][1] = enemy
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(rook, Position(row=0, col=1), start_time=0)
    events = arbiter.advance_time(board, 1000)

    assert events[0].king_captured is False


def test_advance_time_before_arrival_does_nothing():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(rook, Position(row=0, col=2), start_time=0)
    events = arbiter.advance_time(board, 500)

    assert events == []
    assert board.piece_at(Position(row=0, col=0)) is rook
    assert board.piece_at(Position(row=0, col=2)) is None


def test_start_motion_sets_piece_state_to_moving():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(rook, Position(row=0, col=1), start_time=0)

    assert rook.state is PieceState.MOVING


def test_arrival_sets_moved_piece_state_to_idle_and_captured_piece_state_to_captured():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    enemy = _piece(Color.BLACK, PieceKind.PAWN, Position(row=0, col=1))
    grid[0][0] = rook
    grid[0][1] = enemy
    board = Board(grid)
    arbiter = RealTimeArbiter()

    arbiter.start_motion(rook, Position(row=0, col=1), start_time=0)
    arbiter.advance_time(board, 1000)

    assert rook.state is PieceState.IDLE
    assert enemy.state is PieceState.CAPTURED
