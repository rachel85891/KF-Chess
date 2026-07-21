"""GameEventPublisher: Decorator around GameEngine, per client_spec.md
§6 - wraps it via composition (an `_engine` attribute), never
modifying or subclassing it, and never touching engine/game_engine.py.

Observer/EventOrderingPolicy are deliberately separate, minimal
contracts (ISP, spec §6/§10): Observer has one method, and
EventOrderingPolicy is a plain callable, not a class - both injectable
(DIP), neither hardcoded here.

JUMP (Stage 11a - wired for real): the constructor now takes a real
ExtraEngine (kungfu_chess/extra/extra_engine.py), not a bare GameEngine
- request_jump needs it directly, and wait() needs it too (see wait's
own docstring for why). GameEventPublisher derives its own GameEngine
reference from `extra_engine.engine` rather than taking both an engine
and an extra_engine as two separate parameters that could be passed
mismatched - a single source of truth for the one GameEngine either
object ever refers to. request_move is completely untouched by this
(verified via diff) - it never needed anything JUMP-specific.

request_jump(cell) publishes a real JumpAccepted on success, reusing
the existing publish_jump_accepted() helper (no longer a stub - see
its own docstring) with from_cell == to_cell == cell: ExtraEngine.
request_jump (re-verified directly) takes a single cell and never
moves the piece there or anywhere else - a jump has no "from/to" the
way a move does, so JumpAccepted's existing from_cell/to_cell fields
are simply both set to the one cell involved, rather than adding a new
single-cell field to JumpAccepted (kungfu_chess/client/events/
game_events.py, deliberately left untouched) or a new event type: the
existing shape already accommodates this, and PieceAnimator's own
JumpAccepted handling (Stage 5) never reads from_cell/to_cell at all,
only piece_id - so nothing downstream needs a shape change to make the
real event work. is_jump remains the actual, explicit discriminator
other consumers (MovesLogObserver, Stage 8) already use to distinguish
a jump from a move - not field-counting or from_cell==to_cell as an
implicit signal.

NOTE - a deliberate, documented side effect of wiring ExtraEngine: this
project's own established convention (main.py/app.py, per the model
layer's migration) already treats JUMP and Promotion as one bundled
"extras" stack via ExtraEngine, never wired separately. Once wait()
calls ExtraEngine.wait() (required for jump landing/interception to
work at all - see wait's own docstring), Promotion
(kungfu_chess/extra/promotion.py)'s apply_promotions also starts
running as part of every wait() call, where it previously never ran
through GameEventPublisher at all (GameEventPublisher.wait() used to
call GameEngine.wait() directly, bypassing ExtraEngine, and therefore
Promotion, entirely). This is consistent with how ExtraEngine is used
everywhere else in this codebase (never JUMP-without-Promotion) and
does not change any EXISTING (pre-Stage-14) test's observable output
(none exercise a pawn reaching the promotion row), but is flagged here
explicitly rather than left as a silent side effect for a future
reader to discover by surprise. Stage 14 is the first stage to make a
real promotion observably visible to Observers at all - see wait()'s
own docstring for the new PromotionEvent this now publishes.

GameEventPublisherError/MotionNotFoundError follow the same
one-class-per-failure-mode convention as
kungfu_chess/model/board.py's BoardError and the client animation
layer's StateConfigError hierarchy: request_move's internal lookup for
the just-started Motion (see its own comment) relies on an invariant
that always holds today - GameEngine.request_move calls
arbiter.start_motion for every accepted move, so the Motion is always
present immediately afterward - but a bare `next(...)` with no default
would let a raw StopIteration escape if that invariant were ever
violated, which is a confusing, unnamed failure for any caller to
debug. Failing loudly with a named, specific exception instead costs
nothing on the (currently unreachable) happy-invariant path.

EVENTBUS INTEGRATION (Stage A2, server track): the constructor now
also accepts an OPTIONAL `event_bus: Optional[EventBus] = None`
(kungfu_chess/bus/event_bus.py, Stage A1 - a generic, layer-agnostic
pub/sub core, fully independent of this class and of chess). This is
NOT a replacement for the existing `_observers`/`subscribe`/`on_event`
mechanism GameLoopRunner already relies on (ScoreObserver,
MovesLogObserver, PieceAnimatorRegistry, SoundManager,
CooldownTracker) - it is a second, additional destination for the
exact same events, for a future server-side WS layer to subscribe to
independently, without that layer ever needing to know the Observer
mechanism exists at all (and vice versa - neither mechanism knows
about the other).

Defaulting to None, not a required parameter: every existing call site
(GameLoopRunner included) constructs this class without knowing
`event_bus` exists yet, and must keep working completely unmodified -
`event_bus=None` byte-for-byte matches this class's pre-A2 behavior
(re-verified directly: `_notify`'s new `if self._event_bus is not
None` guard means the EventBus code path is not merely "harmless" when
None, it never executes a single instruction).

Hooked at exactly ONE call site - `_notify` - not at each of
request_move/wait/request_jump/publish_jump_accepted individually.
Re-read this file fresh before making this change specifically to find
every place events currently reach `_observers`: all four of those
methods already funnel through this same private `_notify(event)`
helper (never call `observer.on_event` directly themselves) - so
`_notify` is the one true "an event was produced" decision point in
this class. Adding the EventBus publish call there, right alongside
the existing `for observer in self._observers` loop, is therefore the
only change needed to reach every event this class ever produces, and
guarantees the two delivery mechanisms can never disagree about which
events fired or in what order: there is no second, parallel place that
decides this independently to fall out of sync with the first.
`ordering_policy` (see wait()'s own docstring) is applied once, before
`_notify` is ever called per event - both destinations therefore also
agree on ORDER, not just on which events occurred.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Protocol, Sequence

from kungfu_chess.bus.event_bus import EventBus
from kungfu_chess.client.events.game_events import (
    GameOver,
    JumpAccepted,
    JumpLanded,
    MoveAccepted,
    MoveRejected,
    PieceArrived,
    PromotionEvent,
)
from kungfu_chess.engine.game_engine import MoveResult
from kungfu_chess.extra.extra_engine import ExtraEngine
from kungfu_chess.extra.jump import JUMP_DURATION_MS
from kungfu_chess.model.board import Board
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.motion import ArrivalEvent


class GameEventPublisherError(Exception):
    """Base class for all GameEventPublisher errors, matching
    BoardError/StateConfigError's convention: catchable via this one
    base, or via a specific subclass below."""


class MotionNotFoundError(GameEventPublisherError):
    """request_move's internal Motion lookup found no active motion
    for a piece GameEngine just reported as accepted - an invariant
    violation, not a StopIteration."""


class Observer(Protocol):
    def on_event(self, event: object) -> None: ...


EventOrderingPolicy = Callable[[Sequence[object]], Sequence[object]]


def default_event_ordering_policy(events: Sequence[object]) -> Sequence[object]:
    """Identity: publish in the order GameEngine/ExtraEngine produced
    them (FIFO), per client_spec.md §10's default working assumption."""

    return list(events)


class GameEventPublisher:
    def __init__(
        self,
        extra_engine: ExtraEngine,
        ordering_policy: EventOrderingPolicy = default_event_ordering_policy,
        event_bus: Optional[EventBus] = None,
    ):
        """Wrap an existing ExtraEngine (Decorator/composition, per the
        module docstring) so its outputs - and its wrapped GameEngine's
        - can also be published as client-layer events to subscribed
        Observers.

        Args:
            extra_engine: The ExtraEngine instance to wrap. Never
                modified or subclassed - all calls delegate to it (and,
                via `extra_engine.engine`, to the GameEngine it itself
                wraps). See this module's own docstring for why this
                constructor takes ExtraEngine rather than GameEngine
                directly (a breaking change from before Stage 11a).
            ordering_policy: Callable applied to the batch of events
                built inside wait() before publishing them (see
                default_event_ordering_policy and client_spec.md
                §10). Defaults to FIFO/identity; injectable (DIP) so a
                caller can supply a different policy without
                GameEventPublisher itself changing.
            event_bus: Optional kungfu_chess.bus.EventBus (Stage A1) to
                ALSO publish every event onto, in addition to the
                existing Observer mechanism below - see this module's
                own docstring's "EVENTBUS INTEGRATION" section for the
                full reasoning. Defaults to None, which is a strict
                no-op (Stage A2 backward-compatibility requirement):
                every existing caller that doesn't pass this argument
                keeps behaving exactly as before. Injected (DIP), never
                constructed internally by this class.
        """

        self._extra_engine = extra_engine
        self._engine = extra_engine.engine
        self._ordering_policy = ordering_policy
        self._event_bus = event_bus
        self._observers: List[Observer] = []

    @property
    def board(self) -> Board:
        """Expose the wrapped GameEngine's board, read-only.

        Returns:
            self._engine.board.

        This is the ONE piece of surface area GameEventPublisher needs
        to add for kungfu_chess.input.controller.Controller to accept
        a GameEventPublisher wherever it currently accepts a
        GameEngine: Controller.click reads `self.game_engine.board`
        directly and calls `self.game_engine.request_move(...)` - and
        request_move already exists on GameEventPublisher (it's the
        whole point of this class). board + request_move is therefore
        the COMPLETE set Controller needs, nothing more - .state and
        .arbiter are deliberately NOT added here, even though
        GameEngine has them too: nothing in Controller reads either,
        and the one other consumer that does need them
        (view.renderer.build_snapshot, for engine.state.clock_ms and
        engine.arbiter.active_motions()) is designed to receive the
        real GameEngine directly, not go through this publisher at all
        (see kungfu_chess.client.loop.game_loop's own docstring for
        why). Adding .state/.arbiter here anyway would just be unused,
        speculative surface area on a class whose whole design
        principle is wrapping GameEngine, not becoming a second
        GameEngine.
        """

        return self._engine.board

    def subscribe(self, observer: Observer) -> None:
        """Register an Observer to receive every event this publisher
        publishes from now on.

        Args:
            observer: Any object implementing Observer's single
                on_event(event) method. No unsubscribe is provided -
                not needed yet by any current caller.

        Returns:
            None.
        """

        self._observers.append(observer)

    def _notify(self, event: object) -> None:
        """Deliver one event to every currently-subscribed Observer,
        in subscription order - and, if an EventBus was injected (see
        __init__'s `event_bus` param and this module's "EVENTBUS
        INTEGRATION" docstring section), ALSO publish it there.

        Args:
            event: The event instance to deliver (one of the frozen
                dataclasses in game_events.py).

        Returns:
            None.

        This is the SINGLE call site every public method on this class
        (request_move, wait, publish_jump_accepted) already routes
        through to reach _observers - adding the EventBus publish call
        here, rather than at each of those call sites individually,
        is what guarantees the two delivery mechanisms can never
        observe a different set/order of events from one another.
        """

        for observer in self._observers:
            observer.on_event(event)

        if self._event_bus is not None:
            self._event_bus.publish(event)

    def request_move(self, from_cell: Position, to_cell: Position) -> MoveResult:
        """Request a move via the wrapped GameEngine, and publish
        MoveAccepted or MoveRejected based on its real MoveResult.

        Args:
            from_cell: The Position the moving piece currently
                occupies.
            to_cell: The Position it is being requested to move to.

        Returns:
            The original MoveResult from GameEngine.request_move,
            unchanged - callers that only use the return value (not
            events) keep working exactly as if GameEventPublisher
            weren't in the call path at all.

        Raises:
            MotionNotFoundError: See this module's docstring and
                MotionNotFoundError's own docstring - guards an
                invariant that always holds today, not a normal,
                user-triggerable condition.
        """

        piece = self._engine.board.piece_at(from_cell)

        result = self._engine.request_move(from_cell, to_cell)

        if result.is_accepted:
            # piece.cell only updates on arrival (RealTimeArbiter), so
            # the just-started Motion for this exact piece is still
            # findable by identity right after request_move returns.
            motion = next((m for m in self._engine.arbiter.active_motions() if m.piece is piece), None)
            if motion is None:
                raise MotionNotFoundError(
                    f"no active motion found for piece_id={piece.id} after an accepted move "
                    f"{from_cell} -> {to_cell}"
                )
            self._notify(
                MoveAccepted(
                    piece_id=piece.id,
                    from_cell=from_cell,
                    to_cell=to_cell,
                    duration_ms=motion.arrival_time - motion.start_time,
                )
            )
        else:
            self._notify(MoveRejected(reason=result.reason))

        return result

    def wait(self, ms: int) -> List[ArrivalEvent]:
        """Advance the wrapped engine's clock by ms, and publish a
        PieceArrived (and a GameOver, if a king was captured) for each
        resulting ArrivalEvent, plus a JumpLanded for each jump landing
        that resolved, in the order this publisher's EventOrderingPolicy
        produces.

        Args:
            ms: Milliseconds of logical time to advance, forwarded
                as-is to ExtraEngine.wait.

        Returns:
            The arrival_events element of ExtraEngine.wait's 4-tuple,
            unchanged - callers that only use the return value (not
            events) keep working exactly as if GameEventPublisher
            weren't in the call path at all. Identical to what
            GameEngine.wait(ms) alone would have returned whenever no
            JUMP is in flight (ExtraEngine.wait's own
            JumpTracker.resolve_due call is then a no-op) - i.e.
            unchanged for every scenario this class's existing tests
            already cover.

        Calls ExtraEngine.wait(ms), NOT GameEngine.wait(ms) directly
        (re-verified from extra_engine.py fresh before making this
        change): ExtraEngine.wait already calls self.engine.wait(ms)
        as part of its own implementation, ordered around driving
        JumpTracker.resolve_due against the same target clock - calling
        GameEngine.wait(ms) here as well would advance the clock twice
        in one call. This is also what actually makes JUMP landing/
        interception happen at all (see module docstring) - without
        this, an accepted jump would start but never resolve.
        interception_events (ExtraEngine.wait's first return value) is
        deliberately not turned into a published event here - out of
        this stage's JUMP-only scope; a future stage can add an
        InterceptionEvent-style event the same way this one adds
        JumpAccepted. `promoted` (ExtraEngine.wait's fourth return
        value) IS now turned into a published PromotionEvent (Stage
        14) - previously discarded entirely (`_promoted`), since
        nothing consumed it before Stage 14's SoundManager needed a
        real, distinguishable promotion trigger. Each promoted piece is
        matched back to its own arrival by piece_id (below) and
        published as a PromotionEvent right after that arrival's own
        PieceArrived - safe to match this way because apply_promotions
        (kungfu_chess/extra/promotion.py, re-verified directly) only
        ever appends a piece it found by iterating this exact
        arrival_events batch, so every id in `promoted` is guaranteed
        to belong to exactly one arrival already in this loop.

        `landing_events` (ExtraEngine.wait's second return value, new -
        closes client_spec.md §10's documented gap) is turned into one
        published JumpLanded per landing, the same way arrival_events
        become PieceArrived: JumpTracker.resolve_due (via
        ExtraEngine.wait) is the real, authoritative point a jump's
        cooldown starts, and until now nothing published that moment at
        all - CooldownTracker (kungfu_chess/client/events/
        cooldown_tracker.py) could only ever react to ordinary
        PieceArrived. See game_events.py's own JumpLanded docstring for
        why this is a NEW event type rather than a reused PieceArrived.
        """

        _interception_events, landing_events, arrival_events, promoted = self._extra_engine.wait(ms)
        promoted_piece_ids = {piece.id for piece in promoted}

        pending: List[object] = []
        for landing in landing_events:
            pending.append(JumpLanded(piece_id=landing.piece.id, cell=landing.cell))

        for arrival in arrival_events:
            captured_piece_id: Optional[int] = (
                arrival.captured_piece.id if arrival.captured_piece is not None else None
            )
            pending.append(
                PieceArrived(piece_id=arrival.piece.id, cell=arrival.destination, captured_piece_id=captured_piece_id)
            )
            if arrival.king_captured:
                pending.append(GameOver(winner_color=arrival.captured_piece.color.opposite))
            if arrival.piece.id in promoted_piece_ids:
                # arrival.piece.kind is already the promoted kind here:
                # apply_promotions (inside ExtraEngine.wait, above)
                # mutates it in place before returning - re-verified
                # directly in extra/promotion.py.
                pending.append(
                    PromotionEvent(piece_id=arrival.piece.id, cell=arrival.destination, new_kind=arrival.piece.kind)
                )

        for event in self._ordering_policy(pending):
            self._notify(event)

        return arrival_events

    def request_jump(self, cell: Position) -> bool:
        """Request a JUMP for whichever piece occupies `cell`, via the
        wrapped ExtraEngine, and publish a real JumpAccepted if it
        succeeds.

        Args:
            cell: The cell the piece to jump currently occupies - a
                single cell, not a from/to pair (see module docstring
                for why: ExtraEngine.request_jump itself only takes
                one cell, since a jump never moves the piece anywhere).

        Returns:
            The original bool from ExtraEngine.request_jump, unchanged
            - True if accepted, False for every rejection case (game
            over, out of bounds, no piece there, already airborne,
            mid-motion, still on cooldown - all re-verified directly
            from ExtraEngine.request_jump's own logic). No
            MoveRejected-style event is published on False:
            MoveRejected's `reason` field is populated from
            RuleEngine's move-legality reasons (kungfu_chess/rules/
            rule_engine.py's MoveValidation.reason strings) -
            ExtraEngine.request_jump exposes no such reason string, only
            a bare bool, so there is nothing honest to put in a
            MoveRejected.reason here without inventing text ExtraEngine
            itself never produced (the same "don't guess/invent fields"
            principle this module's docstring already applies to
            JumpAccepted's own fields). The bool return value already
            communicates the outcome safely to any caller that checks
            it, the same way a plain False already does today for
            ExtraEngine.request_jump's own direct callers.
        """

        piece = self._engine.board.piece_at(cell)
        accepted = self._extra_engine.request_jump(cell)

        if accepted:
            self.publish_jump_accepted(piece_id=piece.id, from_cell=cell, to_cell=cell, duration_ms=JUMP_DURATION_MS)

        return accepted

    def publish_jump_accepted(self, piece_id: int, from_cell: Position, to_cell: Position, duration_ms: int) -> None:
        """No longer a stub (Stage 11a) - called by request_jump above
        for a real accepted jump, with from_cell == to_cell == the
        jumping piece's own cell (see module docstring for why).
        Kept as its own public method, not inlined into request_jump,
        so the "build and publish a JumpAccepted" concern stays in one
        place regardless of how many call sites eventually trigger it."""

        self._notify(JumpAccepted(piece_id=piece_id, from_cell=from_cell, to_cell=to_cell, duration_ms=duration_ms))
