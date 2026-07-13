"""RealTimeArbiter: deterministic real-time move execution, per
spec.md §10.

Accepts only motions whose chess legality has already been checked
elsewhere (RuleEngine) - it never validates legality itself, only
tracks timing and resolves arrivals. Active motions are held outside
the board (self._motions), and the board is mutated only on arrival -
Piece.cell (kept in sync by Board.move_piece, per model/board.py's own
design) therefore still reflects the source cell for the whole transit,
which is exactly what makes "print board" deterministic before/after
arrival per spec.md §10.

Motions are resolved in (arrival_time, sequence) order so that
multiple arrivals due in a single advance_time call settle
deterministically - RealTimeArbiter itself does not restrict how many
motions can be active at once (spec.md §10 describes it as holding "a
collection" of them); the "only one motion in progress" policy belongs
to GameEngine, not here.

Now that GameEngine's motion_in_progress guard is per-piece rather than
global (spec.md §2's "Simultaneous movement of pieces" extension), two
independently-started motions can legally target the same destination
cell. advance_time closes the "declared target captured" sub-case of
that (spec.md §2's "Cancelling an action if the target is captured
before arrival" extension): whenever an arrival captures a piece, every
other still-active motion whose own target was that same piece is
cancelled - removed from _motions, its piece's state reset to IDLE, no
board mutation (the board was never touched for a motion that never
arrived) - and reported as a CancellationEvent, separate from the
ArrivalEvent list, mirroring how extra/jump.py's InterceptionEvent is
returned alongside rather than merged into arrivals. This check runs
immediately when the capture happens, not deferred until the cancelled
motion's own arrival_time - so a motion can be cancelled long before it
was due, and if it also happened to be independently due in the very
same advance_time call (its arrival_time also <= clock_ms), the capture
is still resolved first (motions are processed in (arrival_time,
sequence) order, and the capturing arrival always has a strictly
smaller arrival_time - it already had to happen for there to be a
captured piece to share as a target) - the cancelled motion is then
skipped when the main loop reaches it, rather than double-processed as
an arrival.

advance_time also now runs a general collision check, BEFORE resolving
any due arrivals, closing the remaining gap the paragraph above used to
describe as an accepted limitation (spec.md §2's "Collision between
moving pieces" extension): every pair of currently-active motions is
checked for whether their swept paths - the discrete cells each one's
motion passes through, reusing rules/shapes.py's path_cells exactly as
the existing static _path_is_blocked legality check does, not any new
continuous/pixel geometry - occupy the same cell during overlapping
time windows (see _swept_path and _shared_cell_overlap). A hit
mutually cancels both motions (via cancel_motion, same as any other
cancellation - no capture, no board mutation, state reset to IDLE) and
is reported as a CollisionEvent. This is color-blind, mirroring
_path_is_blocked's own color-blindness - physical space, not capture
legality. It supersedes the old "later arrival just captures whatever's
there" behavior for any case where two motions' paths genuinely overlap
in time, including two motions racing to the same still-empty
destination (previously an accidental capture purely from arrival
order, not a deliberate outcome). Because collision detection runs
before due-resolution and mutates _motions immediately, the due list
computed afterward already excludes anything just cancelled - no
separate "was this already collided away" check is needed there, unlike
the target-captured cancellation above (which happens mid-loop, since
it can only be known partway through resolving arrivals).

Per Motion.target's docstring, Knight-shaped motions are exempt from
_path_is_blocked's path_cells in the first place - path_cells only
terminates for straight-or-diagonal (dr==0, dc==0, or |dr|==|dc|) pairs,
since it steps toward the destination by sign(dr)/sign(dc) each
iteration; calling it for a Knight's (dr, dc) such as (2, 1) would loop
forever, since that step vector never lands exactly on the target. So
_swept_path treats a Knight motion as having no intermediate cells at
all (consistent with knights already being exempt from
_requires_clear_path), with its sole path entry - the destination -
spanning the motion's entire [start_time, arrival_time), rather than a
single MS_PER_SQUARE-wide slice: this keeps Knights fully participating
in destination-level collisions (so a Knight racing another piece to a
shared destination is still caught), while never contributing a false
intermediate-cell hazard.

cancel_motion is used both by the optional extras track (spec.md §2's
JUMP parry mechanic) and internally by advance_time's own
target-captured cancellation above: it removes a specific in-flight
Motion before it resolves - no arrival, no capture - and resets the
piece's state back to IDLE, since a cancelled motion's piece is neither
mid-transit nor captured, just never dispatched. (Extras-track callers
that go on to mark the piece CAPTURED themselves, e.g. JUMP's
interception, simply overwrite this immediately after - this fix does
not change their observed behavior, only closes a latent gap that was
invisible while they were the only caller.)
"""

from __future__ import annotations

import itertools
from typing import Optional

from kungfu_chess.model.board import Board
from kungfu_chess.model.piece import Piece, PieceKind, PieceState
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.motion import ArrivalEvent, CancellationEvent, CollisionEvent, Motion
from kungfu_chess.rules.shapes import path_cells

CELL_SIZE = 100
PIECE_SPEED = 100
MS_PER_SQUARE = int(CELL_SIZE / PIECE_SPEED * 1000)


def _chebyshev_distance(source: Position, destination: Position) -> int:
    return max(abs(destination.row - source.row), abs(destination.col - source.col))


def _swept_path(motion: Motion) -> list[tuple[Position, int, int]]:
    dr = motion.destination.row - motion.source.row
    dc = motion.destination.col - motion.source.col

    if dr == 0 or dc == 0 or abs(dr) == abs(dc):
        intermediate = [
            Position(row=row, col=col)
            for row, col in path_cells(
                motion.source.row, motion.source.col, motion.destination.row, motion.destination.col
            )
        ]
        cells = intermediate + [motion.destination]
        return [
            (cell, motion.start_time + i * MS_PER_SQUARE, motion.start_time + (i + 1) * MS_PER_SQUARE)
            for i, cell in enumerate(cells)
        ]

    return [(motion.destination, motion.start_time, motion.arrival_time)]


def _shared_cell_overlap(motion_a: Motion, motion_b: Motion, clock_ms: int) -> Optional[Position]:
    for cell_a, entry_a, exit_a in _swept_path(motion_a):
        for cell_b, entry_b, exit_b in _swept_path(motion_b):
            if cell_a != cell_b:
                continue
            if entry_a < exit_b and entry_b < exit_a and max(entry_a, entry_b) <= clock_ms:
                return cell_a
    return None


class RealTimeArbiter:
    def __init__(self):
        self._motions: list[Motion] = []
        self._sequence_counter = 0

    def _next_sequence(self) -> int:
        self._sequence_counter += 1
        return self._sequence_counter

    def has_active_motion(self) -> bool:
        return len(self._motions) > 0

    def is_piece_moving(self, piece: Piece) -> bool:
        return any(motion.piece is piece for motion in self._motions)

    def active_motions(self) -> tuple[Motion, ...]:
        return tuple(self._motions)

    def cancel_motion(self, motion: Motion) -> bool:
        try:
            self._motions.remove(motion)
            motion.piece.state = PieceState.IDLE
            return True
        except ValueError:
            return False

    def start_motion(self, piece: Piece, destination: Position, start_time: int, board: Board) -> Motion:
        squares = _chebyshev_distance(piece.cell, destination)
        motion = Motion(
            piece=piece,
            source=piece.cell,
            destination=destination,
            start_time=start_time,
            arrival_time=start_time + squares * MS_PER_SQUARE,
            sequence=self._next_sequence(),
            target=board.piece_at(destination),
        )
        self._motions.append(motion)
        piece.state = PieceState.MOVING
        return motion

    def advance_time(
        self, board: Board, clock_ms: int
    ) -> tuple[list[ArrivalEvent], list[CancellationEvent], list[CollisionEvent]]:
        collisions: list[CollisionEvent] = []
        for motion_a, motion_b in itertools.combinations(sorted(self._motions, key=lambda motion: motion.sequence), 2):
            if motion_a not in self._motions or motion_b not in self._motions:
                continue  # one of them was already cancelled earlier in this same pass
            cell = _shared_cell_overlap(motion_a, motion_b, clock_ms)
            if cell is None:
                continue
            self.cancel_motion(motion_a)
            self.cancel_motion(motion_b)
            collisions.append(CollisionEvent(piece_a=motion_a.piece, piece_b=motion_b.piece, cell=cell, time=clock_ms))

        due = sorted(
            (motion for motion in self._motions if motion.arrival_time <= clock_ms),
            key=lambda motion: (motion.arrival_time, motion.sequence),
        )

        events: list[ArrivalEvent] = []
        cancellations: list[CancellationEvent] = []
        for motion in due:
            if motion not in self._motions:
                continue  # cancelled earlier in this same pass, see below
            self._motions.remove(motion)

            captured_piece = board.piece_at(motion.destination)
            if captured_piece is not None:
                board.remove_piece(motion.destination)
                captured_piece.state = PieceState.CAPTURED

            board.move_piece(motion.source, motion.destination)
            motion.piece.state = PieceState.IDLE

            events.append(
                ArrivalEvent(
                    piece=motion.piece,
                    source=motion.source,
                    destination=motion.destination,
                    captured_piece=captured_piece,
                    king_captured=captured_piece is not None and captured_piece.kind == PieceKind.KING,
                )
            )

            if captured_piece is not None:
                targeting = [m for m in self._motions if m.target is captured_piece]
                for cancelled_motion in targeting:
                    self.cancel_motion(cancelled_motion)
                    cancellations.append(
                        CancellationEvent(
                            piece=cancelled_motion.piece,
                            source=cancelled_motion.source,
                            destination=cancelled_motion.destination,
                            target=captured_piece,
                        )
                    )

        return events, cancellations, collisions
