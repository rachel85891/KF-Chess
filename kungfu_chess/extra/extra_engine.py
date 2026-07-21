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

wait()'s return value grew a fourth element (landing_events, closing
client_spec.md §10's documented gap): JumpTracker.resolve_due now
returns its own landing events alongside interception_events (see
jump.py's own docstring) - this method simply forwards that second
value through unchanged, exactly like it already forwards
interception_events and promoted. GameEventPublisher.wait is the one
place that turns these into a real, observable JumpLanded per landing
(see its own docstring) - this class stays event-agnostic, same as it
already is for interception_events/promoted today.

GAME-OVER VIA INTERCEPTION (closing the gap where a King destroyed via
interception never actually ended the game): wait() now also sets
self.engine.state.game_over = True when any interception_event's own
king_captured is True, mirroring GameEngine.wait's own identical
one-line check over arrival_events - but that check runs entirely
inside self.engine.wait, which never sees interception_events at all
(a separate value this class alone assembles from JumpTracker), so it
could never have caught this case on its own. This class is the
correct - and only - place to add it: jump.py's own resolve_due has no
GameEngine.state reference to mutate (see its own docstring), and this
class already holds a real `self.engine` reference. This stays
event-agnostic exactly like the rest of this class (no GameOver client
event is built here - that conversion happens only in
GameEventPublisher.wait, same as AttackerIntercepted/JumpLanded
already do).
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

    def wait(self, ms: int) -> Tuple[list, list, List[ArrivalEvent], list]:
        target_clock_ms = self.engine.state.clock_ms + ms
        interception_events, landing_events = self.jumps.resolve_due(target_clock_ms, self.engine.arbiter, self.engine.board)

        # A King destroyed via interception must end the game exactly
        # like one lost to an ordinary arrival-based capture - mirrors
        # GameEngine.wait's own identical one-line check over
        # arrival_events below, applied here to interception_events
        # instead. This is the one place that CAN make this mutation:
        # jump.py's own resolve_due has no GameEngine.state reference to
        # set it from (see jump.py's own docstring), and self.engine.wait
        # below only ever inspects its own arrival_events, never
        # interception_events - so without this line, self.engine.wait's
        # own state.game_over = True would never fire for this case at
        # all, leaving request_move/request_jump's existing game_over
        # guards silently un-triggered despite a King already destroyed.
        for interception in interception_events:
            if interception.king_captured:
                self.engine.state.game_over = True

        arrival_events = self.engine.wait(ms)
        promoted = apply_promotions(self.engine.board, arrival_events)

        return interception_events, landing_events, arrival_events, promoted
