"""Active-motion data structures for RealTimeArbiter, per spec.md §10.

Motion is the record of a move in transit: fixed at start_motion time
(source/destination/timing/a tie-break sequence number), never mutated
afterward. ArrivalEvent is what advance_time reports back once a
Motion resolves - the caller (a future GameEngine) inspects
king_captured to learn about a king capture without RealTimeArbiter
importing or calling into a GameEngine class, which would invert the
dependency direction spec.md §3 establishes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from kungfu_chess.model.piece import Piece
from kungfu_chess.model.position import Position


@dataclass(frozen=True)
class Motion:
    piece: Piece
    source: Position
    destination: Position
    start_time: int
    arrival_time: int
    sequence: int


@dataclass(frozen=True)
class ArrivalEvent:
    piece: Piece
    source: Position
    destination: Position
    captured_piece: Optional[Piece]
    king_captured: bool
