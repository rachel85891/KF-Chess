from __future__ import annotations

from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.model.position import Position


def test_pixel_to_cell_converts_correctly():
    mapper = BoardMapper()

    assert mapper.pixel_to_cell(0, 0) == Position(row=0, col=0)
    assert mapper.pixel_to_cell(99, 99) == Position(row=0, col=0)
    assert mapper.pixel_to_cell(100, 100) == Position(row=1, col=1)
    assert mapper.pixel_to_cell(250, 150) == Position(row=1, col=2)
