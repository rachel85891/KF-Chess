"""Pure unit tests for server/algebraic_notation.py - no networking, no
GameSession, no board at all. The row/col mapping asserted here is not
guessed: it is re-derived from server/game_session.py's own
STANDARD_STARTING_POSITION_LINES (White's back rank on row 7, Black's
on row 0) and kungfu_chess/rules/piece_rules.py's own _pawn_start_row
(white pawns start on board.height - 2 = row 6, black on row 1) -
cross-checked below against several concrete, known squares from that
exact starting position, not just one.
"""

from __future__ import annotations

import pytest

from kungfu_chess.model.position import Position
from server.algebraic_notation import InvalidSquareError, algebraic_to_position


def test_a1_is_the_bottom_left_corner_whites_queenside_rook_square():
    assert algebraic_to_position("a1") == Position(row=7, col=0)


def test_h1_is_the_bottom_right_corner_whites_kingside_rook_square():
    assert algebraic_to_position("h1") == Position(row=7, col=7)


def test_a8_is_the_top_left_corner_blacks_queenside_rook_square():
    assert algebraic_to_position("a8") == Position(row=0, col=0)


def test_h8_is_the_top_right_corner_blacks_kingside_rook_square():
    assert algebraic_to_position("h8") == Position(row=0, col=7)


def test_e1_is_whites_king_starting_square():
    # STANDARD_STARTING_POSITION_LINES row 7: "wR wN wB wQ wK wB wN wR"
    # - col 4 is wK.
    assert algebraic_to_position("e1") == Position(row=7, col=4)


def test_e8_is_blacks_king_starting_square():
    # STANDARD_STARTING_POSITION_LINES row 0: "bR bN bB bQ bK bB bN bR"
    # - col 4 is bK.
    assert algebraic_to_position("e8") == Position(row=0, col=4)


def test_e2_is_whites_e_pawn_starting_square():
    # kungfu_chess/rules/piece_rules.py's _pawn_start_row: white pawns
    # start on board.height - 2 = row 6 (8-row board).
    assert algebraic_to_position("e2") == Position(row=6, col=4)


def test_e7_is_blacks_e_pawn_starting_square():
    # _pawn_start_row: black pawns start on row 1.
    assert algebraic_to_position("e7") == Position(row=1, col=4)


def test_e4_is_two_squares_forward_from_whites_e_pawn():
    assert algebraic_to_position("e4") == Position(row=4, col=4)


def test_file_letter_is_case_insensitive():
    assert algebraic_to_position("E2") == algebraic_to_position("e2")


def test_wrong_length_raises_invalid_square_error():
    with pytest.raises(InvalidSquareError):
        algebraic_to_position("e22")


def test_invalid_file_letter_raises_invalid_square_error():
    with pytest.raises(InvalidSquareError):
        algebraic_to_position("z2")


def test_invalid_rank_digit_raises_invalid_square_error():
    with pytest.raises(InvalidSquareError):
        algebraic_to_position("e9")


def test_non_digit_rank_raises_invalid_square_error():
    with pytest.raises(InvalidSquareError):
        algebraic_to_position("ex")
