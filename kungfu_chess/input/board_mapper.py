"""BoardMapper: pixel <-> cell coordinate conversion, per spec.md §11.

Reuses CELL_SIZE from realtime.real_time_arbiter rather than
redeclaring 100 as a new magic number - the same cell-size constant
spec.md §10 already established. The shared track has no scrolling
camera (spec.md §11's Camera/Viewport decision) - viewport support, if
ever added, belongs here, not in the model.
"""

from __future__ import annotations

from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import CELL_SIZE


class BoardMapper:
    def pixel_to_cell(self, x: int, y: int) -> Position:
        return Position(row=y // CELL_SIZE, col=x // CELL_SIZE)
