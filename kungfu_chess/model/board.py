"""Board: the logical grid Position -> Piece mapping, per spec.md §5.3.

Board keeps Piece.cell in sync with the grid whenever it writes to a
cell (add_piece, move_piece). Board owns "logical occupancy" (spec.md
§3) - it is the only component with full visibility into where every
piece actually sits, so it is the natural place to prevent
Piece.cell and the grid from silently disagreeing. remove_piece is the
one exception: once a piece is off the board there is no board-cell
left to sync to, so the removed piece keeps its last on-board cell
rather than being reset to a sentinel value.

Rejects double occupancy (and other broken invariants: moving from or
removing an empty cell, writing out of bounds) by raising, not by
returning a bool/result. By the time anything calls into Board, the
future RuleEngine (spec.md §8) is expected to have already validated
legality - a rejection reaching Board means an invariant was already
broken upstream, which should fail loudly rather than be silently
ignorable.

Originally coexisted with the legacy kungfu_chess.domain.board.Board
during the migration; that class has since been retired along with
the rest of the domain/services/infrastructure/presentation
architecture, leaving this as the only Board.
"""

from __future__ import annotations

from typing import Optional

from kungfu_chess.model.piece import Piece
from kungfu_chess.model.position import Position


class BoardError(Exception):
    pass


class OutOfBoundsError(BoardError):
    pass


class CellOccupiedError(BoardError):
    pass


class EmptyCellError(BoardError):
    pass


class Board:
    def __init__(self, grid: list[list[Optional[Piece]]]):
        self.height = len(grid)
        self.width = len(grid[0]) if grid else 0
        self._cells: dict[Position, Piece] = {}

        for row_index, row in enumerate(grid):
            for col_index, piece in enumerate(row):
                if piece is not None:
                    self.add_piece(Position(row=row_index, col=col_index), piece)

    def in_bounds(self, cell: Position) -> bool:
        return 0 <= cell.row < self.height and 0 <= cell.col < self.width

    def piece_at(self, cell: Position) -> Optional[Piece]:
        return self._cells.get(cell)

    def add_piece(self, cell: Position, piece: Piece) -> None:
        if not self.in_bounds(cell):
            raise OutOfBoundsError(f"{cell} is outside the board")
        if cell in self._cells:
            raise CellOccupiedError(f"{cell} is already occupied")

        self._cells[cell] = piece
        piece.cell = cell

    def remove_piece(self, cell: Position) -> Piece:
        if cell not in self._cells:
            raise EmptyCellError(f"{cell} has no piece to remove")

        return self._cells.pop(cell)

    def move_piece(self, source: Position, destination: Position) -> None:
        if source not in self._cells:
            raise EmptyCellError(f"{source} has no piece to move")
        if not self.in_bounds(destination):
            raise OutOfBoundsError(f"{destination} is outside the board")
        if destination in self._cells:
            raise CellOccupiedError(f"{destination} is already occupied")

        piece = self._cells.pop(source)
        self._cells[destination] = piece
        piece.cell = destination
