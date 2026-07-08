"""Board: the logical grid API the rest of the domain/services layer
talks to. It never exposes how cells are physically stored - that is
delegated to a BoardStorage implementation (Bridge pattern), so a future
packed/binary representation can replace ListBoardStorage without any
caller of Board changing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator, Optional

from kungfu_chess.domain.piece import Piece


class BoardStorage(ABC):
    @property
    @abstractmethod
    def num_rows(self) -> int:
        raise NotImplementedError

    @property
    @abstractmethod
    def num_cols(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def get(self, row: int, col: int) -> Optional[Piece]:
        raise NotImplementedError

    @abstractmethod
    def set(self, row: int, col: int, piece: Optional[Piece]) -> None:
        raise NotImplementedError


class ListBoardStorage(BoardStorage):
    """Default in-memory storage: a list of lists of Piece|None."""

    def __init__(self, grid: list[list[Optional[Piece]]]):
        self._grid = grid
        self._num_rows = len(grid)
        self._num_cols = len(grid[0]) if grid else 0

    @property
    def num_rows(self) -> int:
        return self._num_rows

    @property
    def num_cols(self) -> int:
        return self._num_cols

    def get(self, row: int, col: int) -> Optional[Piece]:
        return self._grid[row][col]

    def set(self, row: int, col: int, piece: Optional[Piece]) -> None:
        self._grid[row][col] = piece


class Board:
    def __init__(self, storage: BoardStorage):
        self._storage = storage

    @classmethod
    def from_grid(cls, grid: list[list[Optional[Piece]]]) -> "Board":
        return cls(ListBoardStorage(grid))

    @property
    def num_rows(self) -> int:
        return self._storage.num_rows

    @property
    def num_cols(self) -> int:
        return self._storage.num_cols

    def in_bounds(self, row: int, col: int) -> bool:
        return 0 <= row < self.num_rows and 0 <= col < self.num_cols

    def get_piece(self, row: int, col: int) -> Optional[Piece]:
        return self._storage.get(row, col)

    def set_piece(self, row: int, col: int, piece: Optional[Piece]) -> None:
        self._storage.set(row, col, piece)

    def iter_cells(self) -> Iterator[tuple[int, int, Optional[Piece]]]:
        for row in range(self.num_rows):
            for col in range(self.num_cols):
                yield row, col, self._storage.get(row, col)
