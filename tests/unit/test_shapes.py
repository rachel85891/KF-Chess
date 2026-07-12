from __future__ import annotations

import pytest

from kungfu_chess.model.color import Color
from kungfu_chess.rules.shapes import (
    is_bishop_move,
    is_king_move,
    is_knight_move,
    is_pawn_move,
    is_queen_move,
    is_rook_move,
    path_cells,
)


# ---------------------------------------------------------------------
# King
# ---------------------------------------------------------------------

@pytest.mark.parametrize("dr,dc", [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)])
def test_king_one_cell_any_direction_is_legal(dr, dc):
    assert is_king_move(dr, dc, Color.WHITE, is_capture=False, is_start_row=False) is True


@pytest.mark.parametrize("dr,dc", [(0, 0), (0, 2), (2, 0), (2, 2), (1, 2)])
def test_king_beyond_one_cell_or_null_is_illegal(dr, dc):
    assert is_king_move(dr, dc, Color.WHITE, is_capture=False, is_start_row=False) is False


# ---------------------------------------------------------------------
# Knight
# ---------------------------------------------------------------------

@pytest.mark.parametrize("dr,dc", [(1, 2), (2, 1), (-1, 2), (-2, -1), (2, -1), (-1, -2)])
def test_knight_l_shapes_are_legal(dr, dc):
    assert is_knight_move(dr, dc, Color.WHITE, False, False) is True


@pytest.mark.parametrize("dr,dc", [(0, 0), (1, 1), (2, 2), (1, 0), (3, 1)])
def test_knight_non_l_shapes_are_illegal(dr, dc):
    assert is_knight_move(dr, dc, Color.WHITE, False, False) is False


# ---------------------------------------------------------------------
# Rook / Bishop / Queen
# ---------------------------------------------------------------------

def test_rook_moves_any_distance_orthogonally():
    assert is_rook_move(0, 5, Color.WHITE, False, False) is True
    assert is_rook_move(-3, 0, Color.WHITE, False, False) is True


def test_rook_cannot_move_diagonally_or_off_axis_or_null():
    assert is_rook_move(2, 2, Color.WHITE, False, False) is False
    assert is_rook_move(2, 3, Color.WHITE, False, False) is False
    assert is_rook_move(0, 0, Color.WHITE, False, False) is False


def test_bishop_moves_any_distance_diagonally():
    assert is_bishop_move(3, 3, Color.WHITE, False, False) is True
    assert is_bishop_move(-2, 2, Color.WHITE, False, False) is True


def test_bishop_cannot_move_orthogonally_or_null():
    assert is_bishop_move(0, 4, Color.WHITE, False, False) is False
    assert is_bishop_move(0, 0, Color.WHITE, False, False) is False


def test_queen_combines_rook_and_bishop():
    assert is_queen_move(0, 4, Color.WHITE, False, False) is True
    assert is_queen_move(4, 4, Color.WHITE, False, False) is True
    assert is_queen_move(1, 2, Color.WHITE, False, False) is False


# ---------------------------------------------------------------------
# Pawn
# ---------------------------------------------------------------------

def test_white_pawn_single_forward_step_non_capture():
    assert is_pawn_move(-1, 0, Color.WHITE, is_capture=False, is_start_row=False) is True


def test_black_pawn_single_forward_step_non_capture():
    assert is_pawn_move(1, 0, Color.BLACK, is_capture=False, is_start_row=False) is True


def test_pawn_straight_move_is_never_a_capture():
    assert is_pawn_move(-1, 0, Color.WHITE, is_capture=True, is_start_row=False) is False


def test_pawn_double_step_only_from_start_row():
    assert is_pawn_move(-2, 0, Color.WHITE, is_capture=False, is_start_row=True) is True
    assert is_pawn_move(-2, 0, Color.WHITE, is_capture=False, is_start_row=False) is False


def test_pawn_diagonal_move_requires_capture():
    assert is_pawn_move(-1, 1, Color.WHITE, is_capture=True, is_start_row=False) is True
    assert is_pawn_move(-1, 1, Color.WHITE, is_capture=False, is_start_row=False) is False


def test_pawn_wrong_direction_is_illegal():
    assert is_pawn_move(1, 0, Color.WHITE, is_capture=False, is_start_row=False) is False


# ---------------------------------------------------------------------
# path_cells geometry
# ---------------------------------------------------------------------

def test_path_cells_horizontal():
    assert path_cells(0, 0, 0, 3) == [(0, 1), (0, 2)]


def test_path_cells_vertical():
    assert path_cells(0, 0, 3, 0) == [(1, 0), (2, 0)]


def test_path_cells_diagonal():
    assert path_cells(0, 0, 3, 3) == [(1, 1), (2, 2)]


def test_path_cells_adjacent_is_empty():
    assert path_cells(0, 0, 0, 1) == []
