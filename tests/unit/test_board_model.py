from __future__ import annotations

import pytest

from kungfu_chess.domain.color import Color
from kungfu_chess.model.board import Board, CellOccupiedError, EmptyCellError, OutOfBoundsError
from kungfu_chess.model.piece import Piece, PieceKind
from kungfu_chess.model.position import Position


def _pawn(cell: Position) -> Piece:
    return Piece(color=Color.WHITE, kind=PieceKind.PAWN, cell=cell)


def _empty_grid(rows: int, cols: int) -> list[list[None]]:
    return [[None for _ in range(cols)] for _ in range(rows)]


def test_board_dimensions_are_inferred_from_grid():
    board = Board(_empty_grid(rows=3, cols=2))

    assert board.height == 3
    assert board.width == 2


def test_empty_cell_returns_no_piece():
    board = Board(_empty_grid(rows=2, cols=2))

    assert board.piece_at(Position(row=0, col=0)) is None


def test_occupied_cell_returns_the_correct_piece():
    piece = _pawn(Position(row=0, col=0))
    grid = _empty_grid(rows=2, cols=2)
    grid[0][0] = piece
    board = Board(grid)

    assert board.piece_at(Position(row=0, col=0)) is piece


def test_adding_two_pieces_to_the_same_cell_fails():
    board = Board(_empty_grid(rows=2, cols=2))
    cell = Position(row=0, col=0)
    board.add_piece(cell, _pawn(cell))

    with pytest.raises(CellOccupiedError):
        board.add_piece(cell, _pawn(cell))


def test_moving_a_piece_updates_source_and_destination():
    source = Position(row=0, col=0)
    destination = Position(row=1, col=1)
    piece = _pawn(source)
    grid = _empty_grid(rows=2, cols=2)
    grid[0][0] = piece
    board = Board(grid)

    board.move_piece(source, destination)

    assert board.piece_at(source) is None
    assert board.piece_at(destination) is piece


def test_removing_a_captured_piece_clears_its_cell():
    cell = Position(row=0, col=0)
    piece = _pawn(cell)
    grid = _empty_grid(rows=2, cols=2)
    grid[0][0] = piece
    board = Board(grid)

    removed = board.remove_piece(cell)

    assert removed is piece
    assert board.piece_at(cell) is None


def test_add_piece_updates_pieces_cell_to_match_board_position():
    board = Board(_empty_grid(rows=2, cols=2))
    cell = Position(row=1, col=0)
    piece = _pawn(Position(row=0, col=0))

    board.add_piece(cell, piece)

    assert piece.cell == cell


def test_move_piece_updates_pieces_cell_to_match_destination():
    source = Position(row=0, col=0)
    destination = Position(row=1, col=1)
    piece = _pawn(source)
    grid = _empty_grid(rows=2, cols=2)
    grid[0][0] = piece
    board = Board(grid)

    board.move_piece(source, destination)

    assert piece.cell == destination


def test_remove_piece_does_not_modify_pieces_cell():
    cell = Position(row=0, col=0)
    piece = _pawn(cell)
    grid = _empty_grid(rows=2, cols=2)
    grid[0][0] = piece
    board = Board(grid)

    removed = board.remove_piece(cell)

    assert removed.cell == cell


def test_add_piece_out_of_bounds_raises():
    board = Board(_empty_grid(rows=2, cols=2))

    with pytest.raises(OutOfBoundsError):
        board.add_piece(Position(row=5, col=5), _pawn(Position(row=5, col=5)))


def test_move_piece_onto_occupied_cell_raises():
    source = Position(row=0, col=0)
    blocked_destination = Position(row=1, col=1)
    grid = _empty_grid(rows=2, cols=2)
    grid[0][0] = _pawn(source)
    grid[1][1] = _pawn(blocked_destination)
    board = Board(grid)

    with pytest.raises(CellOccupiedError):
        board.move_piece(source, blocked_destination)


def test_moving_from_an_empty_cell_raises():
    board = Board(_empty_grid(rows=2, cols=2))

    with pytest.raises(EmptyCellError):
        board.move_piece(Position(row=0, col=0), Position(row=1, col=1))


def test_removing_from_an_empty_cell_raises():
    board = Board(_empty_grid(rows=2, cols=2))

    with pytest.raises(EmptyCellError):
        board.remove_piece(Position(row=0, col=0))


def test_in_bounds_reports_correctly():
    board = Board(_empty_grid(rows=2, cols=2))

    assert board.in_bounds(Position(row=0, col=0)) is True
    assert board.in_bounds(Position(row=1, col=1)) is True
    assert board.in_bounds(Position(row=2, col=0)) is False
    assert board.in_bounds(Position(row=0, col=-1)) is False
