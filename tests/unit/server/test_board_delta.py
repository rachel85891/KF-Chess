"""Unit tests for server/application/board_delta.py - pure, no server,
no networking, mirroring tests/unit/server/test_elo_rating.py's own
"plain function of plain data" testing style."""

from __future__ import annotations

from server.application.board_delta import board_to_occupancy, compute_board_delta
from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece, PieceKind
from kungfu_chess.model.position import Position


def _grid(rows: int, cols: int) -> list:
    return [[None for _ in range(cols)] for _ in range(rows)]


def test_compute_board_delta_returns_exactly_the_two_changed_cells():
    a1 = Position(row=0, col=0)
    a2 = Position(row=1, col=0)
    b1 = Position(row=0, col=1)

    previous = {
        a1: (Color.WHITE, PieceKind.ROOK),
        a2: None,
        b1: (Color.BLACK, PieceKind.PAWN),
    }
    current = {
        a1: None,  # the rook moved away from a1
        a2: (Color.WHITE, PieceKind.ROOK),  # ...and landed on a2
        b1: (Color.BLACK, PieceKind.PAWN),  # unchanged
    }

    delta = compute_board_delta(previous, current)

    assert delta == {
        a1: None,
        a2: (Color.WHITE, PieceKind.ROOK),
    }


def test_compute_board_delta_is_empty_when_nothing_changed():
    a1 = Position(row=0, col=0)
    snapshot = {a1: (Color.WHITE, PieceKind.KING)}

    delta = compute_board_delta(snapshot, dict(snapshot))

    assert delta == {}


def test_compute_board_delta_treats_a_missing_previous_key_as_empty():
    a1 = Position(row=0, col=0)
    previous: dict = {}
    current = {a1: (Color.WHITE, PieceKind.KING)}

    delta = compute_board_delta(previous, current)

    assert delta == {a1: (Color.WHITE, PieceKind.KING)}


def test_board_to_occupancy_reflects_every_cell_including_empty_ones():
    grid = _grid(2, 2)
    mover = Piece(color=Color.WHITE, kind=PieceKind.ROOK, cell=Position(row=0, col=0))
    grid[0][0] = mover
    board = Board(grid)

    occupancy = board_to_occupancy(board)

    assert occupancy == {
        Position(row=0, col=0): (Color.WHITE, PieceKind.ROOK),
        Position(row=0, col=1): None,
        Position(row=1, col=0): None,
        Position(row=1, col=1): None,
    }
