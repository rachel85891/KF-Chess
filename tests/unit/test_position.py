from __future__ import annotations

import dataclasses

import pytest

from kungfu_chess.model.position import Position


def test_positions_with_same_row_and_col_are_equal():
    assert Position(row=2, col=3) == Position(row=2, col=3)


@pytest.mark.parametrize(
    "other",
    [
        Position(row=9, col=3),
        Position(row=2, col=9),
        Position(row=9, col=9),
    ],
)
def test_positions_with_different_row_or_col_are_not_equal(other):
    assert Position(row=2, col=3) != other


def test_position_repr_is_readable():
    assert repr(Position(row=3, col=4)) == "Position(row=3, col=4)"


def test_position_is_immutable():
    position = Position(row=1, col=1)

    with pytest.raises(dataclasses.FrozenInstanceError):
        position.row = 5
