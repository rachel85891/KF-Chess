"""ExtraEngine: wraps a core GameEngine from the outside to add JUMP
and Promotion support, per spec.md §2, without modifying
engine/game_engine.py at all. Composition, not inheritance or
monkeypatching - the wrapped GameEngine remains fully usable on its
own (e.g. GameEngine.request_move still works exactly as the core
spec defines it; ExtraEngine only adds request_jump and its own wait).

request_jump's own guards (is_airborne, active_motions) are
independent of GameEngine.request_move's guards by design (see
jump.py's docstring) - but its available_at_ms check below is a
deliberate symmetry addition, not core reuse: a piece just landed from
a JUMP (kungfu_chess/extra/jump.py sets available_at_ms on landing) is
gated from an ordinary move by request_move's existing cooldown_active
guard, so it is gated here too, from jumping again immediately,
matching request_jump's existing bool-return rejection style rather
than inventing a new one.
"""

from __future__ import annotations

from typing import List, Tuple

from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.extra.jump import JumpTracker
from kungfu_chess.extra.promotion import apply_promotions
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.motion import ArrivalEvent


class ExtraEngine:
    def __init__(self, engine: GameEngine):
        self.engine = engine
        self.jumps = JumpTracker()

    def request_jump(self, cell: Position) -> bool:
        if self.engine.state.game_over:
            return False
        if not self.engine.board.in_bounds(cell):
            return False

        piece = self.engine.board.piece_at(cell)
        if piece is None:
            return False
        if self.jumps.is_airborne(piece.id):
            return False
        if any(motion.piece is piece for motion in self.engine.arbiter.active_motions()):
            return False
        if self.engine.state.clock_ms < piece.available_at_ms:
            return False

        self.jumps.start_jump(piece, self.engine.state.clock_ms)
        return True

    def wait(self, ms: int) -> Tuple[list, List[ArrivalEvent], list]:
        target_clock_ms = self.engine.state.clock_ms + ms
        interception_events = self.jumps.resolve_due(target_clock_ms, self.engine.arbiter, self.engine.board)

        arrival_events = self.engine.wait(ms)
        promoted = apply_promotions(self.engine.board, arrival_events)

        return interception_events, arrival_events, promoted
