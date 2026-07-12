"""Piece: a single piece instance on the board, per spec.md §5.2.

Mutable, unlike domain.piece.Piece. That class is a value object: Board
owns the row/col -> Piece mapping externally, and a Piece there is
never mutated. This Piece is different - cell and state are fields of
the piece itself, and spec.md §3 assigns "piece lifecycle state" to
the Model layer. That makes id the piece's identity (not its field
values), i.e. an entity rather than a value object, and entities are
conventionally mutable: state and cell change in place as a piece
moves through idle -> moving -> captured, without every holder of a
reference needing to swap to a freshly-replaced instance.

id is assigned by the constructor from a module-level counter
(init=False - callers cannot supply their own id), matching spec's
"IDs are assigned at creation time, in the constructor." This is
simple and deterministic within a process, at the cost of being
process-global mutable state; acceptable here since nothing depends on
specific id values, only on ids being unique.

Coexists with kungfu_chess.domain.piece.Piece for now - unifying the
two is a deliberately deferred decision, not an oversight.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from itertools import count

from kungfu_chess.model.color import Color
from kungfu_chess.model.position import Position

_id_counter = count()


class PieceKind(Enum):
    KING = "K"
    QUEEN = "Q"
    ROOK = "R"
    BISHOP = "B"
    KNIGHT = "N"
    PAWN = "P"


class PieceState(Enum):
    IDLE = "idle"
    MOVING = "moving"
    CAPTURED = "captured"


@dataclass
class Piece:
    id: int = field(init=False, default_factory=lambda: next(_id_counter))
    color: Color
    kind: PieceKind
    cell: Position
    state: PieceState = PieceState.IDLE
