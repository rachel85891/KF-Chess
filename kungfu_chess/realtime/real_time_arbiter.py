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
"""

from __future__ import annotations

from kungfu_chess.model.board import Board
from kungfu_chess.model.piece import Piece, PieceKind, PieceState
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.motion import ArrivalEvent, Motion

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

    def start_motion(self, piece: Piece, destination: Position, start_time: int) -> Motion:
        squares = _chebyshev_distance(piece.cell, destination)
        motion = Motion(
            piece=piece,
            source=piece.cell,
            destination=destination,
            start_time=start_time,
            arrival_time=start_time + squares * MS_PER_SQUARE,
            sequence=self._next_sequence(),
        )
        self._motions.append(motion)
        piece.state = PieceState.MOVING
        return motion

    def advance_time(self, board: Board, clock_ms: int) -> list[ArrivalEvent]:
        due = sorted(
            (motion for motion in self._motions if motion.arrival_time <= clock_ms),
            key=lambda motion: (motion.arrival_time, motion.sequence),
        )

        events: list[ArrivalEvent] = []
        for motion in due:
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

        return events
