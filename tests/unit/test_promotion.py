from __future__ import annotations

from kungfu_chess.domain.color import Color
from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.extra.promotion import apply_promotions
from kungfu_chess.model.board import Board
from kungfu_chess.model.piece import Piece, PieceKind
from kungfu_chess.model.position import Position


def _empty_grid(rows: int, cols: int) -> list[list[None]]:
    return [[None for _ in range(cols)] for _ in range(rows)]


def _piece(color: Color, kind: PieceKind, cell: Position) -> Piece:
    return Piece(color=color, kind=kind, cell=cell)


def test_pawn_arriving_on_back_rank_promotes_to_queen():
    grid = _empty_grid(3, 3)
    pawn = _piece(Color.WHITE, PieceKind.PAWN, Position(row=1, col=0))
    grid[1][0] = pawn
    board = Board(grid)
    engine = GameEngine(board)
    engine.request_move(Position(row=1, col=0), Position(row=0, col=0))
    arrival_events = engine.wait(1000)

    apply_promotions(board, arrival_events)

    assert pawn.kind is PieceKind.QUEEN


def test_pawn_arriving_elsewhere_does_not_promote():
    grid = _empty_grid(4, 3)
    pawn = _piece(Color.WHITE, PieceKind.PAWN, Position(row=2, col=0))
    grid[2][0] = pawn
    board = Board(grid)
    engine = GameEngine(board)
    engine.request_move(Position(row=2, col=0), Position(row=1, col=0))
    arrival_events = engine.wait(1000)

    apply_promotions(board, arrival_events)

    assert pawn.kind is PieceKind.PAWN
