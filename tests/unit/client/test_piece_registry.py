from __future__ import annotations

import pytest

from kungfu_chess.client.events.piece_registry import PieceInfo, PieceRegistry, UnknownPieceIdError
from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece, PieceKind
from kungfu_chess.model.position import Position


def _empty_grid(rows: int, cols: int) -> list[list[None]]:
    return [[None for _ in range(cols)] for _ in range(rows)]


def _piece(color: Color, kind: PieceKind, cell: Position) -> Piece:
    return Piece(color=color, kind=kind, cell=cell)


def test_from_board_captures_kind_and_color_for_every_piece():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    king = _piece(Color.BLACK, PieceKind.KING, Position(row=2, col=2))
    pawn = _piece(Color.WHITE, PieceKind.PAWN, Position(row=1, col=1))
    grid[0][0] = rook
    grid[2][2] = king
    grid[1][1] = pawn
    board = Board(grid)

    registry = PieceRegistry.from_board(board)

    assert registry.info_for(rook.id) == PieceInfo(kind=PieceKind.ROOK, color=Color.WHITE)
    assert registry.info_for(king.id) == PieceInfo(kind=PieceKind.KING, color=Color.BLACK)
    assert registry.info_for(pawn.id) == PieceInfo(kind=PieceKind.PAWN, color=Color.WHITE)


def test_info_for_raises_unknown_piece_id_error_naming_the_id():
    grid = _empty_grid(2, 2)
    board = Board(grid)
    registry = PieceRegistry.from_board(board)

    with pytest.raises(UnknownPieceIdError) as exc_info:
        registry.info_for(9999)

    assert "9999" in str(exc_info.value)
