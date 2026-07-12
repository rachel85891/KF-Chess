from __future__ import annotations

from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece, PieceKind
from kungfu_chess.model.position import Position


def _empty_grid(rows: int, cols: int) -> list[list[None]]:
    return [[None for _ in range(cols)] for _ in range(rows)]


def _piece(color: Color, kind: PieceKind, cell: Position) -> Piece:
    return Piece(color=color, kind=kind, cell=cell)


def test_request_move_rejected_when_game_over():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    engine = GameEngine(board)
    engine.state.game_over = True

    result = engine.request_move(Position(row=0, col=0), Position(row=0, col=1))

    assert result.is_accepted is False
    assert result.reason == "game_over"


def test_request_move_rejected_when_any_motion_active_opposite_color():
    grid = _empty_grid(3, 3)
    white_rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    black_rook = _piece(Color.BLACK, PieceKind.ROOK, Position(row=2, col=0))
    grid[0][0] = white_rook
    grid[2][0] = black_rook
    board = Board(grid)
    engine = GameEngine(board)
    engine.request_move(Position(row=0, col=0), Position(row=0, col=1))

    result = engine.request_move(Position(row=2, col=0), Position(row=2, col=1))

    assert result.is_accepted is False
    assert result.reason == "motion_in_progress"


def test_request_move_rejected_when_any_motion_active_same_color():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    other_rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=2, col=0))
    grid[0][0] = rook
    grid[2][0] = other_rook
    board = Board(grid)
    engine = GameEngine(board)
    engine.request_move(Position(row=0, col=0), Position(row=0, col=1))

    result = engine.request_move(Position(row=2, col=0), Position(row=2, col=1))

    assert result.is_accepted is False
    assert result.reason == "motion_in_progress"


def test_request_move_rejected_with_rule_engine_reason_on_illegal_move():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    friendly = _piece(Color.WHITE, PieceKind.PAWN, Position(row=0, col=1))
    grid[0][0] = rook
    grid[0][1] = friendly
    board = Board(grid)
    engine = GameEngine(board)

    result = engine.request_move(Position(row=0, col=0), Position(row=0, col=1))

    assert result.is_accepted is False
    assert result.reason == "friendly_destination"


def test_request_move_accepted_and_starts_motion_on_legal_move():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    engine = GameEngine(board)

    result = engine.request_move(Position(row=0, col=0), Position(row=0, col=2))

    assert result.is_accepted is True
    assert result.reason == "ok"
    assert engine.arbiter.has_active_motion() is True


def test_wait_advances_clock_and_settles_due_motions():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    engine = GameEngine(board)
    engine.request_move(Position(row=0, col=0), Position(row=0, col=1))

    events = engine.wait(1000)

    assert engine.state.clock_ms == 1000
    assert len(events) == 1
    assert board.piece_at(Position(row=0, col=1)) is rook


def test_wait_sets_game_over_on_king_capture_arrival():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    king = _piece(Color.BLACK, PieceKind.KING, Position(row=0, col=1))
    grid[0][0] = rook
    grid[0][1] = king
    board = Board(grid)
    engine = GameEngine(board)
    engine.request_move(Position(row=0, col=0), Position(row=0, col=1))

    engine.wait(1000)

    assert engine.state.game_over is True


def test_request_move_rejected_after_game_over_even_if_otherwise_legal():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    king = _piece(Color.BLACK, PieceKind.KING, Position(row=0, col=1))
    other_white = _piece(Color.WHITE, PieceKind.PAWN, Position(row=2, col=2))
    grid[0][0] = rook
    grid[0][1] = king
    grid[2][2] = other_white
    board = Board(grid)
    engine = GameEngine(board)
    engine.request_move(Position(row=0, col=0), Position(row=0, col=1))
    engine.wait(1000)

    result = engine.request_move(Position(row=2, col=2), Position(row=1, col=2))

    assert result.is_accepted is False
    assert result.reason == "game_over"
