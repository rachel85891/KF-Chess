"""Unit tests for kungfu_chess/notation/algebraic_notation.py - the
shared, client-and-server-importable relocation of what used to live
only at server/algebraic_notation.py (Stage B3). server/
algebraic_notation.py's own pre-existing test file
(tests/unit/server/test_algebraic_notation.py) is untouched and keeps
testing the one-directional square->Position conversion through the
old import path (now a thin re-export shim) - this file instead proves
the NEW, shared module directly, plus the new reverse direction
(Position->square) neither the old module nor its test ever had.
"""

from __future__ import annotations

import pytest

from kungfu_chess.model.position import Position
from kungfu_chess.notation.algebraic_notation import (
    InvalidPositionError,
    InvalidSquareError,
    algebraic_to_position,
    position_to_algebraic,
)

# A spread of real board squares - both back ranks' corners, both
# colors' pawn rows, and a center square - not just one square, per
# this stage's own requirement.
_SQUARES = ["a1", "h1", "a8", "h8", "e1", "e8", "e2", "e7", "e4", "d5"]


@pytest.mark.parametrize("square", _SQUARES)
def test_square_to_position_to_square_round_trips(square):
    assert position_to_algebraic(algebraic_to_position(square)) == square


@pytest.mark.parametrize(
    "position",
    [
        Position(row=7, col=0),  # a1
        Position(row=7, col=7),  # h1
        Position(row=0, col=0),  # a8
        Position(row=0, col=7),  # h8
        Position(row=6, col=4),  # e2
        Position(row=1, col=4),  # e7
        Position(row=4, col=4),  # e4
    ],
)
def test_position_to_square_to_position_round_trips(position):
    assert algebraic_to_position(position_to_algebraic(position)) == position


def test_position_to_algebraic_produces_the_expected_literal_strings():
    # Cross-checked directly against the same known-square facts
    # algebraic_to_position's own docstring/tests already establish -
    # not just "round trips with itself", but the actual expected text.
    assert position_to_algebraic(Position(row=7, col=0)) == "a1"
    assert position_to_algebraic(Position(row=0, col=7)) == "h8"
    assert position_to_algebraic(Position(row=7, col=4)) == "e1"
    assert position_to_algebraic(Position(row=6, col=4)) == "e2"


def test_algebraic_to_position_still_raises_invalid_square_error_for_bad_input():
    with pytest.raises(InvalidSquareError):
        algebraic_to_position("z9")


def test_position_to_algebraic_raises_for_a_position_outside_the_8x8_board():
    with pytest.raises(InvalidPositionError):
        position_to_algebraic(Position(row=8, col=0))


def test_position_to_algebraic_raises_for_a_negative_position():
    with pytest.raises(InvalidPositionError):
        position_to_algebraic(Position(row=0, col=-1))
