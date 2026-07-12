"""GameEngine: orchestration only, per spec.md §9 - coordinates calls
to Board, RuleEngine, and RealTimeArbiter, and holds/points to the
mutable GameState (game_over, clock_ms). It never reimplements
legality or timing logic itself.

request_move enforces at most one motion per piece (per spec.md §2's
"Simultaneous movement of pieces" extension), checked via
RealTimeArbiter.is_piece_moving(piece) against the piece at from_cell.
This replaces an earlier, stricter reading of spec.md §2 ("there can
only be one legal motion in progress at a time") that blocked every
other request system-wide, with no per-piece or per-color exception,
whenever any motion was active anywhere on the board - that global
guard was itself a deliberate departure from the original
services/game_engine.py prototype, which blocked only the opposing
color and let same-color moves run in parallel. Scoping the guard to
the specific piece being requested is a further, explicitly-approved
relaxation: any two different pieces may now move concurrently: only a
piece that is itself still mid-motion rejects a new request for
itself.

Deliberately out of scope for this step: GameSnapshot generation for
the Renderer/BoardPrinter (also mentioned in spec.md §9). Renderer
(§12) and BoardPrinter don't exist yet, so building a snapshot
interface now would be speculative - deferred, not forgotten.

last_cancellations exposes the CancellationEvents from the most recent
wait() call (spec.md §2's "Cancelling an action if the target is
captured before arrival" extension) as a plain instance attribute
rather than as part of wait()'s return value. This is a deliberate
trade-off, not an oversight: wait(ms) -> list[ArrivalEvent] is a
preserved external contract that kungfu_chess/extra/extra_engine.py
depends on byte-for-byte (it does
`arrival_events = self.engine.wait(ms)` and hands that straight to
apply_promotions, which iterates it expecting ArrivalEvent objects) -
changing wait's return shape to also carry cancellations would silently
break that call without any change to extra/ itself, which is out of
bounds. Reading last_cancellations right after a wait() call gives
tests (and future consumers - Renderer, BoardPrinter) a way to observe
cancellations without touching wait's signature at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from kungfu_chess.model.board import Board
from kungfu_chess.model.game_state import GameState
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.motion import ArrivalEvent, CancellationEvent
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.rules.rule_engine import RuleEngine


@dataclass(frozen=True)
class MoveResult:
    is_accepted: bool
    reason: str


class GameEngine:
    def __init__(self, board: Board):
        self.board = board
        self.state = GameState()
        self.rule_engine = RuleEngine()
        self.arbiter = RealTimeArbiter()
        self.last_cancellations: list[CancellationEvent] = []

    def request_move(self, from_cell: Position, to_cell: Position) -> MoveResult:
        if self.state.game_over:
            return MoveResult(is_accepted=False, reason="game_over")

        piece = self.board.piece_at(from_cell)
        if piece is not None and self.arbiter.is_piece_moving(piece):
            return MoveResult(is_accepted=False, reason="motion_in_progress")

        validation = self.rule_engine.validate_move(self.board, from_cell, to_cell)
        if not validation.is_valid:
            return MoveResult(is_accepted=False, reason=validation.reason)

        self.arbiter.start_motion(piece, to_cell, self.state.clock_ms, self.board)
        return MoveResult(is_accepted=True, reason="ok")

    def wait(self, ms: int) -> list[ArrivalEvent]:
        self.state.clock_ms += ms
        events, cancellations = self.arbiter.advance_time(self.board, self.state.clock_ms)
        self.last_cancellations = cancellations

        for event in events:
            if event.king_captured:
                self.state.game_over = True

        return events
