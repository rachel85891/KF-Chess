"""CooldownTracker: per-piece cooldown timer, per client_spec.md §2's
"Cooldown after a move" extension. Design patterns: Observer
(implements Stage 3's single-method Observer protocol itself) +
Registry (a piece_id -> cooldown-start/duration lookup, the same
pattern-vocabulary convention as PieceAnimatorRegistry, Stage 10a).

SCOPE - BOTH ordinary move cooldown AND JUMP's post-landing cooldown:
kungfu_chess/realtime/real_time_arbiter.py's COOLDOWN_MS (the fixed
cooldown GameEngine already applies to every genuine arrival,
re-imported here rather than re-hardcoded) is recorded the moment a
PieceArrived fires; kungfu_chess/extra/jump.py's JUMP_COOLDOWN_MS
(also re-imported, never re-hardcoded) is recorded the moment a
JumpLanded fires - a real, published event for the exact moment a
jump's cooldown starts (closing client_spec.md §10's previously
documented gap: JumpTracker used to resolve landings entirely
internally to ExtraEngine.wait, with no client-visible signal at all;
see kungfu_chess/extra/jump.py's own docstring and
kungfu_chess/client/events/game_events.py's JumpLanded docstring for
the full reasoning behind that event's shape and why it is a distinct
type rather than a reused PieceArrived). Because the two kinds of
cooldown have different durations, this class now records not just
WHEN a piece's cooldown started but WHICH duration applies to it
(`_cooldown_duration_ms`, alongside the existing `_cooldown_start_ms`)
- remaining_ratio reads the duration back per piece_id rather than
assuming COOLDOWN_MS for every cooldown, which is what would happen if
this were left a single fixed module-level divisor.

WHY this class needs to be TOLD the current clock_ms, both at
recording time and at query time, rather than reading a GameEngine
reference itself: re-checked game_events.py directly - PieceArrived
carries no timestamp at all (piece_id, cell, captured_piece_id only).
And holding a live GameEngine/ExtraEngine reference would be the exact
thing this codebase's other Observers (ScoreObserver, MovesLogObserver,
PieceAnimatorRegistry) already deliberately avoid (DIP) - none of them
reach for a live engine, they only ever react to what an event itself
carries or what they're separately, explicitly given. So there are
exactly two places this class can learn "what time is it": recording a
cooldown's start (on_event, when a PieceArrived fires) and querying how
much of it remains (remaining_ratio). Neither the event nor this
class's own state can supply that value - only the caller (GameLoopRunner,
the one place allowed to hold a live engine reference) can, via
set_current_clock_ms() before wait() is called and via
remaining_ratio()'s own current_clock_ms parameter at query/render
time.

WHY set_current_clock_ms() must be called BEFORE publisher.wait(), not
after: GameEventPublisher.wait() already fully advances
GameEngine.state.clock_ms (via ExtraEngine.wait -> GameEngine.wait)
BEFORE it publishes any PieceArrived (re-verified directly from
event_publisher.py: _notify calls happen only after
self._extra_engine.wait(ms) has already returned) - so by the time
on_event fires, the real clock has already moved to its new value. The
composition root can predict that exact value ahead of time
(engine.state.clock_ms + delta_ms, since wait(ms)'s only clock mutation
is a plain += ms) and hand it to this tracker first, so it is already
cached and ready the instant on_event needs it during the
synchronous wait() call that follows.

ERROR HANDLING: no new exception type is introduced here, and none is
needed. Every input this class can receive already has a safe,
well-defined result rather than an error condition: an unknown
piece_id in remaining_ratio() returns 0.0 (a piece that has never
arrived simply has no active cooldown - normal, not exceptional), and
an already-elapsed cooldown also returns 0.0 rather than a negative
ratio. on_event/set_current_clock_ms only ever store plain values,
with no validation-worthy failure mode of their own.
"""

from __future__ import annotations

from typing import Dict

from kungfu_chess.client.events.game_events import JumpLanded, PieceArrived
from kungfu_chess.extra.jump import JUMP_COOLDOWN_MS
from kungfu_chess.realtime.real_time_arbiter import COOLDOWN_MS


class CooldownTracker:
    def __init__(self) -> None:
        """Holds no engine/board reference (DIP) - only piece_id ->
        cooldown-start-clock_ms and piece_id -> cooldown-duration maps
        it builds up entirely from PieceArrived/JumpLanded events and
        set_current_clock_ms() calls."""

        self._current_clock_ms: int = 0
        self._cooldown_start_ms: Dict[int, int] = {}
        self._cooldown_duration_ms: Dict[int, int] = {}

    def set_current_clock_ms(self, current_clock_ms: int) -> None:
        """Tell this tracker what the current logical clock is - see
        module docstring for why this must be called (by the
        composition root) before every publisher.wait() call, using
        the clock value that call is about to produce.

        Args:
            current_clock_ms: The clock_ms value to use for any
                cooldown recorded by on_event until this is called
                again.

        Returns:
            None.
        """

        self._current_clock_ms = current_clock_ms

    def on_event(self, event: object) -> None:
        """On a real PieceArrived or JumpLanded, record that piece's
        cooldown as starting at whatever clock_ms was most recently
        supplied via set_current_clock_ms(), using the duration that
        matches the event's own kind (COOLDOWN_MS for an ordinary
        arrival, JUMP_COOLDOWN_MS for a jump landing) - matching the
        "match on the relevant types, ignore the rest" OCP pattern
        every other Observer in this codebase already follows: a
        future 7th event type needs no change here.

        Args:
            event: Any published client-layer event.

        Returns:
            None.
        """

        if isinstance(event, PieceArrived):
            self._start_cooldown(event.piece_id, COOLDOWN_MS)
        elif isinstance(event, JumpLanded):
            self._start_cooldown(event.piece_id, JUMP_COOLDOWN_MS)

    def _start_cooldown(self, piece_id: int, duration_ms: int) -> None:
        """Shared recording step for either cooldown kind - keeps
        on_event a plain type dispatch, not a place where the actual
        bookkeeping (two dicts, kept in sync) is duplicated per event
        type."""

        self._cooldown_start_ms[piece_id] = self._current_clock_ms
        self._cooldown_duration_ms[piece_id] = duration_ms

    def remaining_ratio(self, piece_id: int, current_clock_ms: int) -> float:
        """How much of piece_id's currently recorded cooldown - move or
        jump, whichever started it - is still remaining, as a fraction.

        Args:
            piece_id: The piece to query.
            current_clock_ms: The current logical clock, supplied by
                the caller at query/render time (see module docstring
                - this class never reads a clock on its own).

        Returns:
            1.0 immediately after the piece's cooldown-starting event,
            linearly decreasing to 0.0 once that cooldown's own
            duration (COOLDOWN_MS or JUMP_COOLDOWN_MS, whichever
            started it) has fully elapsed. Also 0.0 - not an error, the
            normal, common case for most pieces most of the time - if
            this tracker has no recorded cooldown for piece_id at all,
            or if current_clock_ms indicates the cooldown has already
            fully elapsed.
        """

        start_ms = self._cooldown_start_ms.get(piece_id)
        if start_ms is None:
            return 0.0

        duration_ms = self._cooldown_duration_ms[piece_id]
        elapsed_ms = current_clock_ms - start_ms
        if elapsed_ms <= 0:
            return 1.0
        if elapsed_ms >= duration_ms:
            return 0.0

        return 1.0 - (elapsed_ms / duration_ms)
