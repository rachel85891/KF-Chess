"""Active-motion data structures for RealTimeArbiter, per spec.md §10.

Motion is the record of a move in transit: fixed at start_motion time
(source/destination/timing/a tie-break sequence number), never mutated
afterward. ArrivalEvent is what advance_time reports back once a
Motion resolves - the caller (a future GameEngine) inspects
king_captured to learn about a king capture without RealTimeArbiter
importing or calling into a GameEngine class, which would invert the
dependency direction spec.md §3 establishes.

target is a one-time snapshot, per spec.md §2's "Cancelling an action
if the target is captured before arrival" extension: whichever piece (if
any) occupied destination at start_motion time, never re-evaluated
afterward. It is always either None (the motion wasn't a capture
attempt) or an enemy piece - RuleEngine's friendly_destination check
already makes it structurally impossible for a legal motion to ever
target a friendly piece, so target has no separate same-color case to
guard against here. CancellationEvent is what advance_time reports for
a motion voided because its target was captured by a different motion's
arrival first - see RealTimeArbiter.advance_time's docstring for
exactly how that's detected and ordered.

CollisionEvent is what advance_time reports for a pair of motions
mutually cancelled because their swept paths occupied the same cell at
overlapping times (spec.md §2's "Collision between moving pieces"
extension) - piece_a is always the motion with the lower sequence
number (the one started first), a fixed, deterministic ordering rather
than an arbitrary pair. It is deliberately color-blind: the same
physical-space reasoning as RuleEngine's existing static
_path_is_blocked check (which also does not exempt same-color pieces),
just applied to two pieces in transit instead of one mover against the
static board.
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
    target: Optional[Piece]


@dataclass(frozen=True)
class ArrivalEvent:
    piece: Piece
    source: Position
    destination: Position
    captured_piece: Optional[Piece]
    king_captured: bool


@dataclass(frozen=True)
class CancellationEvent:
    piece: Piece
    source: Position
    destination: Position
    target: Piece


@dataclass(frozen=True)
class CollisionEvent:
    piece_a: Piece
    piece_b: Piece
    cell: Position
    time: int
