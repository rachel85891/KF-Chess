from __future__ import annotations

import pytest

from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece, PieceKind, PieceState
from kungfu_chess.model.position import Position


def test_piece_assigns_unique_id_at_construction():
    piece_a = Piece(color=Color.WHITE, kind=PieceKind.PAWN, cell=Position(row=1, col=0))
    piece_b = Piece(color=Color.WHITE, kind=PieceKind.PAWN, cell=Position(row=1, col=0))

    assert piece_a.id != piece_b.id


def test_piece_stores_color_kind_cell_state():
    cell = Position(row=0, col=4)
    piece = Piece(color=Color.BLACK, kind=PieceKind.KING, cell=cell, state=PieceState.MOVING)

    assert piece.color is Color.BLACK
    assert piece.kind is PieceKind.KING
    assert piece.cell == cell
    assert piece.state is PieceState.MOVING


def test_piece_state_defaults_to_idle():
    piece = Piece(color=Color.WHITE, kind=PieceKind.ROOK, cell=Position(row=0, col=0))

    assert piece.state is PieceState.IDLE


def test_piece_state_can_transition_idle_to_moving_to_captured():
    piece = Piece(color=Color.WHITE, kind=PieceKind.KNIGHT, cell=Position(row=0, col=1))

    assert piece.state is PieceState.IDLE

    piece.state = PieceState.MOVING
    assert piece.state is PieceState.MOVING

    piece.state = PieceState.CAPTURED
    assert piece.state is PieceState.CAPTURED


def test_piece_cell_can_change_when_piece_moves():
    piece = Piece(color=Color.BLACK, kind=PieceKind.BISHOP, cell=Position(row=2, col=2))

    piece.cell = Position(row=3, col=3)

    assert piece.cell == Position(row=3, col=3)


def test_piece_id_stays_stable_across_state_and_cell_changes():
    piece = Piece(color=Color.WHITE, kind=PieceKind.QUEEN, cell=Position(row=0, col=3))
    original_id = piece.id

    piece.state = PieceState.MOVING
    piece.cell = Position(row=1, col=3)

    assert piece.id == original_id


def test_two_pieces_with_identical_fields_but_different_ids_are_not_equal():
    cell = Position(row=0, col=0)
    piece_a = Piece(color=Color.WHITE, kind=PieceKind.PAWN, cell=cell)
    piece_b = Piece(color=Color.WHITE, kind=PieceKind.PAWN, cell=cell)

    assert piece_a != piece_b


def test_piece_id_cannot_be_passed_via_constructor():
    with pytest.raises(TypeError):
        Piece(id=1, color=Color.WHITE, kind=PieceKind.PAWN, cell=Position(row=0, col=0))


def test_piece_available_at_ms_defaults_to_zero():
    piece = Piece(color=Color.WHITE, kind=PieceKind.ROOK, cell=Position(row=0, col=0))

    assert piece.available_at_ms == 0
