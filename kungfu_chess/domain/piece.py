"""PieceType: the pluggable definition of a kind of piece (letter, shape
rule, whether capturing it ends the game, what it promotes into). New
piece types - including ones for a user-defined custom game - are built
by assembling one of these, not by editing engine code.

Piece: a single piece instance sitting on the board (a color plus a
PieceType). Immutable value object - "moving" a piece never mutates a
Piece, it relocates which cell holds a reference to one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from kungfu_chess.domain.color import Color

# (dr, dc, color, is_capture, is_start_row) -> bool
MovementRule = Callable[[int, int, Color, bool, bool], bool]
# (dr, dc) -> bool
PathCheckRule = Callable[[int, int], bool]


@dataclass(frozen=True)
class PieceType:
    letter: str
    name: str
    movement_rule: MovementRule
    requires_clear_path: PathCheckRule
    is_royal: bool = False
    promotes_to: Optional["PieceType"] = None


@dataclass(frozen=True)
class Piece:
    color: Color
    piece_type: PieceType

    @property
    def letter(self) -> str:
        return self.piece_type.letter

    @property
    def is_royal(self) -> bool:
        return self.piece_type.is_royal
