import pytest

from kungfu_chess.config.piece_registry import (
    MOVE_RULES,
    PIECE_NAMES,
    PROMOTIONS,
    REQUIRES_CLEAR_PATH,
    ROYAL_LETTERS,
    PieceTypeRegistry,
)
from kungfu_chess.domain.color import Color
from kungfu_chess.domain.movement.path import path_cells
from kungfu_chess.domain.movement.rules import (
    is_bishop_move,
    is_king_move,
    is_knight_move,
    is_pawn_move,
    is_queen_move,
    is_rook_move,
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


# ---------------------------------------------------------------------
# config.piece_registry function dictionaries
# ---------------------------------------------------------------------

def test_move_rules_covers_every_standard_letter():
    assert set(MOVE_RULES) == set("KQRBNP")


def test_requires_clear_path_mirrors_move_rules_keys():
    assert set(REQUIRES_CLEAR_PATH) == set(MOVE_RULES)


def test_requires_clear_path_true_only_for_sliders_and_pawn_double_step():
    assert REQUIRES_CLEAR_PATH["K"](1, 1) is False
    assert REQUIRES_CLEAR_PATH["N"](1, 2) is False
    assert REQUIRES_CLEAR_PATH["Q"](0, 5) is True
    assert REQUIRES_CLEAR_PATH["R"](0, 5) is True
    assert REQUIRES_CLEAR_PATH["B"](3, 3) is True
    assert REQUIRES_CLEAR_PATH["P"](-2, 0) is True
    assert REQUIRES_CLEAR_PATH["P"](-1, 0) is False


def test_piece_names_and_royal_letters_cover_every_letter():
    assert set(PIECE_NAMES) == set(MOVE_RULES)
    assert ROYAL_LETTERS == {"K"}
    assert PROMOTIONS == {"P": "Q"}


# ---------------------------------------------------------------------
# PieceTypeRegistry.standard_chess()
# ---------------------------------------------------------------------

def test_standard_chess_registry_has_all_six_letters():
    registry = PieceTypeRegistry.standard_chess()
    for letter in "KQRBNP":
        assert registry.has_letter(letter)
    assert registry.has_letter("X") is False


def test_standard_chess_only_king_is_royal():
    registry = PieceTypeRegistry.standard_chess()
    for letter in "KQRBNP":
        assert registry.get(letter).is_royal == (letter == "K")


def test_standard_chess_only_pawn_promotes_and_promotes_to_queen():
    registry = PieceTypeRegistry.standard_chess()
    queen = registry.get("Q")
    pawn = registry.get("P")

    assert pawn.promotes_to is queen
    for letter in "KQRBN":
        assert registry.get(letter).promotes_to is None


def test_standard_chess_registry_movement_rule_and_path_check_are_wired_correctly():
    registry = PieceTypeRegistry.standard_chess()
    rook = registry.get("R")

    assert rook.movement_rule is is_rook_move
    assert rook.requires_clear_path(0, 5) is True


# ---------------------------------------------------------------------
# valid_tokens: the nested-loop-generated constant token set
# ---------------------------------------------------------------------

def test_valid_tokens_is_exactly_the_cross_product_of_colors_and_letters():
    registry = PieceTypeRegistry.standard_chess()
    expected = {f"{color.value}{letter}" for color in Color for letter in "KQRBNP"}
    assert registry.valid_tokens == expected
    assert len(registry.valid_tokens) == 12


def test_valid_tokens_rejects_unknown_letters_and_malformed_tokens():
    registry = PieceTypeRegistry.standard_chess()
    assert "wX" not in registry.valid_tokens
    assert "w" not in registry.valid_tokens
    assert "wKQ" not in registry.valid_tokens
