"""GameEventPublisher: Decorator around GameEngine, per client_spec.md
§6 - wraps it via composition (an `_engine` attribute), never
modifying or subclassing it, and never touching engine/game_engine.py.

Observer/EventOrderingPolicy are deliberately separate, minimal
contracts (ISP, spec §6/§10): Observer has one method, and
EventOrderingPolicy is a plain callable, not a class - both injectable
(DIP), neither hardcoded here.

JUMP: ExtraEngine.request_jump (kungfu_chess/extra/extra_engine.py)
currently returns a bare bool, and JumpTracker (extra/jump.py) never
moves the piece (it stays airborne "at its own cell") - neither exposes
piece_id/from_cell/to_cell/duration_ms the way GameEngine.request_move's
MoveResult + RealTimeArbiter.Motion do for MoveAccepted. Wrapping
ExtraEngine automatically would mean inventing fields client_spec.md
§5/§6 explicitly says must come from the real source, not be guessed.
publish_jump_accepted() below is therefore a deliberate stub: it lets a
future stage publish a real JumpAccepted once ExtraEngine exposes
enough to fill it in honestly, without GameEventPublisher's public
shape needing to change again then.

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
"""

from __future__ import annotations

from typing import Callable, List, Optional, Protocol, Sequence

from kungfu_chess.client.events.game_events import (
    GameOver,
    JumpAccepted,
    MoveAccepted,
    MoveRejected,
    PieceArrived,
)
from kungfu_chess.engine.game_engine import GameEngine, MoveResult
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
    def __init__(self, engine: GameEngine, ordering_policy: EventOrderingPolicy = default_event_ordering_policy):
        """Wrap an existing GameEngine (Decorator/composition, per the
        module docstring) so its outputs can also be published as
        client-layer events to subscribed Observers.

        Args:
            engine: The GameEngine instance to wrap. Never modified,
                subclassed, or replaced - all calls delegate to it.
            ordering_policy: Callable applied to the batch of events
                built inside wait() before publishing them (see
                default_event_ordering_policy and client_spec.md
                §10). Defaults to FIFO/identity; injectable (DIP) so a
                caller can supply a different policy without
                GameEventPublisher itself changing.
        """

        self._engine = engine
        self._ordering_policy = ordering_policy
        self._observers: List[Observer] = []

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
        in subscription order.

        Args:
            event: The event instance to deliver (one of the frozen
                dataclasses in game_events.py).

        Returns:
            None.
        """

        for observer in self._observers:
            observer.on_event(event)

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
        """Advance the wrapped GameEngine's clock by ms, and publish a
        PieceArrived (and a GameOver, if a king was captured) for each
        resulting ArrivalEvent, in the order this publisher's
        EventOrderingPolicy produces.

        Args:
            ms: Milliseconds of logical time to advance, forwarded
                as-is to GameEngine.wait.

        Returns:
            The original list[ArrivalEvent] from GameEngine.wait,
            unchanged - callers that only use the return value (not
            events) keep working exactly as if GameEventPublisher
            weren't in the call path at all.
        """

        arrival_events = self._engine.wait(ms)

        pending: List[object] = []
        for arrival in arrival_events:
            captured_piece_id: Optional[int] = (
                arrival.captured_piece.id if arrival.captured_piece is not None else None
            )
            pending.append(
                PieceArrived(piece_id=arrival.piece.id, cell=arrival.destination, captured_piece_id=captured_piece_id)
            )
            if arrival.king_captured:
                pending.append(GameOver(winner_color=arrival.captured_piece.color.opposite))

        for event in self._ordering_policy(pending):
            self._notify(event)

        return arrival_events

    def publish_jump_accepted(self, piece_id: int, from_cell: Position, to_cell: Position, duration_ms: int) -> None:
        """STUB - not called from anywhere yet. See module docstring:
        no current ExtraEngine/JumpTracker call site can honestly fill
        in these fields, so nothing wires into this automatically. A
        future stage should call this once request_jump/JumpTracker
        exposes real piece_id/cells/duration for an accepted jump."""

        self._notify(JumpAccepted(piece_id=piece_id, from_cell=from_cell, to_cell=to_cell, duration_ms=duration_ms))
