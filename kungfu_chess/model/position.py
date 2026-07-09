"""Position: a logical (row, col) board coordinate.

Deliberately does not validate that the coordinate lies within any
particular board's bounds - that check belongs to Board, not Position
(spec.md §5.3 separation of concerns).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Position:
    row: int
    col: int
