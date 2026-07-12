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
cell. advance_time now closes the specific "declared target captured"
sub-case of that gap (spec.md §2's "Cancelling an action if the target
is captured before arrival" extension): whenever an arrival captures a
piece, every other still-active motion whose own target was that same
piece is cancelled - removed from _motions, its piece's state reset to
IDLE, no board mutation (the board was never touched for a motion that
never arrived) - and reported as a CancellationEvent, separate from the
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
an arrival. What's still NOT handled here - two motions racing to the
same destination where neither one's target was ever formally
"captured" (e.g. both targeted an empty cell, or a motion's target
merely relocated without being captured, per test coverage in
test_real_time_arbiter.py) - remains the accepted limitation deferred
to the separate "Collision between moving pieces" extension.

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

from kungfu_chess.model.board import Board
from kungfu_chess.model.piece import Piece, PieceKind, PieceState
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.motion import ArrivalEvent, CancellationEvent, Motion

CELL_SIZE = 100
PIECE_SPEED = 100
MS_PER_SQUARE = int(CELL_SIZE / PIECE_SPEED * 1000)


def _chebyshev_distance(source: Position, destination: Position) -> int:
    return max(abs(destination.row - source.row), abs(destination.col - source.col))


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

    def advance_time(self, board: Board, clock_ms: int) -> tuple[list[ArrivalEvent], list[CancellationEvent]]:
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

        return events, cancellations
