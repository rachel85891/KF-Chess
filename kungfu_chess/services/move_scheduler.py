"""MoveScheduler: a generic time-ordered queue of pending moves and
airborne (jumping) pieces. It knows nothing about chess rules - only
"what is scheduled" and "what is due by clock_ms" - so it can be
unit-tested in isolation from board/legality/settlement concerns.

due_events() reproduces the original engine's tie-break exactly: at an
equal timestamp, moves are processed before landings, then ties among
same-kind events break by insertion order. This ordering was verified
against the original implementation's actual behavior (not its
docstring, which incorrectly claimed the opposite) - see the
three_way_tie_moves_before_landings characterization fixture.
"""

from __future__ import annotations

from dataclasses import dataclass

from kungfu_chess.domain.color import Color
from kungfu_chess.domain.piece import Piece

Cell = tuple[int, int]

_MOVE_PRIORITY = 0
_LANDING_PRIORITY = 1


@dataclass
class ScheduledMove:
    from_cell: Cell
    to_cell: Cell
    piece: Piece
    requested_at: int
    arrival: int
    sequence: int


@dataclass
class ScheduledLanding:
    cell: Cell
    piece: Piece
    start_time: int
    land_time: int
    sequence: int


class MoveScheduler:
    def __init__(self):
        self._moves: list[ScheduledMove] = []
        self._landings: list[ScheduledLanding] = []
        self._sequence_counter = 0

    def _next_sequence(self) -> int:
        self._sequence_counter += 1
        return self._sequence_counter

    def schedule_move(self, from_cell: Cell, to_cell: Cell, piece: Piece, requested_at: int, arrival: int) -> ScheduledMove:
        move = ScheduledMove(from_cell, to_cell, piece, requested_at, arrival, self._next_sequence())
        self._moves.append(move)
        return move

    def schedule_landing(self, cell: Cell, piece: Piece, start_time: int, land_time: int) -> ScheduledLanding:
        landing = ScheduledLanding(cell, piece, start_time, land_time, self._next_sequence())
        self._landings.append(landing)
        return landing

    def has_pending_move_from(self, row: int, col: int) -> bool:
        return any(m.from_cell == (row, col) for m in self._moves)

    def has_pending_for_color(self, color: Color) -> bool:
        return any(m.piece.color == color for m in self._moves)

    def is_airborne(self, row: int, col: int) -> bool:
        return any(l.cell == (row, col) for l in self._landings)

    def pending_moves(self) -> list[ScheduledMove]:
        """All scheduled moves regardless of whether they are due yet -
        landing interception must scan every pending move, not just
        the ones due in the current batch."""
        return list(self._moves)

    def has_move(self, move: ScheduledMove) -> bool:
        return move in self._moves

    def remove_move(self, move: ScheduledMove) -> None:
        self._moves.remove(move)

    def remove_landing(self, landing: ScheduledLanding) -> None:
        self._landings.remove(landing)

    def due_events(self, clock_ms: int) -> list[tuple[str, object]]:
        events = []
        for m in self._moves:
            if m.arrival <= clock_ms:
                events.append((m.arrival, _MOVE_PRIORITY, m.sequence, "move", m))
        for l in self._landings:
            if l.land_time <= clock_ms:
                events.append((l.land_time, _LANDING_PRIORITY, l.sequence, "land", l))

        events.sort(key=lambda e: (e[0], e[1], e[2]))
        return [(kind, obj) for (_time, _priority, _seq, kind, obj) in events]
