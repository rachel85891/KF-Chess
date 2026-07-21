"""JumpTracker: JUMP as an optional extra, per spec.md §2. Sourced from
the legacy kungfu_chess/services/{game_engine,move_scheduler,
move_resolver}.py's handle_jump/schedule_landing/is_airborne/
resolve_landing/resolve_move semantics, reimplemented against model
types: a piece becomes airborne AT ITS OWN CELL for a fixed duration -
it never moves. If an enemy motion targets that cell while the piece
is airborne, the ATTACKER is destroyed instead of landing (a parry,
not a movement variant).

Kept entirely independent of the core "one motion system-wide" rule
(spec.md §2): an active jump never blocks GameEngine.request_move, and
an active core motion never blocks a jump request - RealTimeArbiter's
_motions and this tracker's airborne registry are two unrelated
collections. Mixing them would re-entangle exactly the complexity
spec.md §2 defers by calling this an independent "additional optional"
rule rather than a variant of the core movement model.

Piece.state is deliberately left untouched by a jump (stays IDLE) -
"airborne" isn't one of spec.md §5.2's three states, and nothing about
this mechanic functionally requires the core Piece.state to reflect
it; airborne-ness lives only in this tracker's own registry. This
keeps model/piece.py completely unmodified.

Interception has two distinct trigger points, both present in the
legacy resolver and both needed - a golden-master fixture from the
retired characterization suite (air_capture_before_landing) failed
against an implementation that only had the second one:

1. An attacker's own motion resolves while its target is STILL
   airborne (legacy resolve_move's is_airborne check) - checked here
   against each airborne entry's [start_time, land_time) window, so it
   fires correctly even for an attacker whose motion was scheduled
   before the jump even started.
2. The jump's own duration elapses while an enemy motion is already
   in flight toward that cell, regardless of how much travel time that
   attacker has left (legacy resolve_landing's scan over pending
   moves) - this is the one that needs an attacker's motion cancelled
   before it would otherwise resolve normally much later.

Both destroy the attacker and leave the defender untouched. Reproducing
either required one small additive hook on RealTimeArbiter,
cancel_motion(motion) - see its docstring for why it was unavoidable;
nothing else about RealTimeArbiter's timing/resolution logic changed.

Landing - the unconditional `del self._airborne[piece_id]` below, which
fires whether or not an attacking_motion was found, since an
interception destroys the attacker, not the defender - also sets
entry.piece.available_at_ms = entry.land_time + JUMP_COOLDOWN_MS
(spec.md §2's "Cooldown after a move" extension, extended here to
JUMP). This reuses Piece.available_at_ms and GameEngine.request_move's
existing cooldown_active guard verbatim - that guard only reads
state.clock_ms against the field, not who set it, so no change to
request_move was needed. It uses entry.land_time rather than the
resolve_due call's clock_ms, unlike core's clock_ms-based convention in
RealTimeArbiter.advance_time: land_time is the piece's actual scheduled
landing instant, so the cooldown window doesn't get inflated just
because resolve_due happened to be reached late via a large wait().

JumpLandingEvent (closing client_spec.md §10's documented gap): every
landing above - unconditional, same as available_at_ms - now also
appends a JumpLandingEvent(piece=entry.piece, cell=entry.piece.cell) to
resolve_due's own second return value, so ExtraEngine.wait (and, from
there, GameEventPublisher.wait) has a real, observable signal for the
exact moment a jump's cooldown starts - mirroring InterceptionEvent's
own existing convention of a frozen, Piece-carrying dataclass built at
the model layer and handed upward, rather than reaching into the
client layer from here (this module has, and must keep, zero
client/event_publisher imports).

InterceptionEvent.king_captured (closing the gap where a King destroyed
via interception never ended the game at all, unlike one lost to an
ordinary arrival-based capture): computed at both trigger points above,
identically to ArrivalEvent's own king_captured field
(kungfu_chess/realtime/motion.py) - the attacker's kind at the instant
it is destroyed. This module still has, and must keep, zero
client/event_publisher imports, and `resolve_due`'s own signature
(clock_ms, arbiter, board) has no GameEngine.state reference to mutate
even if it wanted to - so this field only carries the raw fact upward;
ExtraEngine.wait (which already holds a real GameEngine reference) is
where that fact actually becomes state.game_over = True, mirroring
GameEngine.wait's own identical one-line pattern for arrival_events.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from kungfu_chess.model.board import Board
from kungfu_chess.model.piece import Piece, PieceKind, PieceState
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import MS_PER_SQUARE, RealTimeArbiter

JUMP_DURATION_MS = MS_PER_SQUARE
JUMP_COOLDOWN_MS = 2000


@dataclass(frozen=True)
class _AirborneEntry:
    piece: Piece
    start_time: int
    land_time: int


@dataclass(frozen=True)
class InterceptionEvent:
    """An attacker was destroyed instead of landing/capturing - see this
    module's own docstring for the two distinct trigger points that can
    produce one.

    king_captured mirrors ArrivalEvent's own field of the same name
    (kungfu_chess/realtime/motion.py) exactly - the attacker's own kind
    at the moment it was destroyed, so a King lost to interception is
    just as detectable as one lost to an ordinary arrival-based
    capture, via the same field name/convention. Computed here, at the
    model layer, rather than left for GameEventPublisher to re-derive
    later - same reasoning as ArrivalEvent's own king_captured: the
    model layer already knows the attacker's kind at destruction time,
    so there is nothing for a later layer to compute freshly."""

    attacker: Piece
    defender: Piece
    cell: Position
    king_captured: bool


@dataclass(frozen=True)
class JumpLandingEvent:
    """A jump landed - piece stayed at its own cell, cooldown starts.
    See this module's own docstring's "JumpLandingEvent" section for
    why this exists (client_spec.md §10's documented gap)."""

    piece: Piece
    cell: Position


class JumpTracker:
    def __init__(self):
        self._airborne: dict[int, _AirborneEntry] = {}

    def is_airborne(self, piece_id: int) -> bool:
        return piece_id in self._airborne

    def start_jump(self, piece: Piece, clock_ms: int) -> None:
        self._airborne[piece.id] = _AirborneEntry(
            piece=piece, start_time=clock_ms, land_time=clock_ms + JUMP_DURATION_MS
        )

    def _airborne_entry_at(self, cell: Position) -> Optional[_AirborneEntry]:
        return next((entry for entry in self._airborne.values() if entry.piece.cell == cell), None)

    def resolve_due(
        self, clock_ms: int, arbiter: RealTimeArbiter, board: Board
    ) -> tuple[list[InterceptionEvent], list[JumpLandingEvent]]:
        events: list[InterceptionEvent] = []
        landings: list[JumpLandingEvent] = []

        # Trigger 1: an attacker due to arrive while its target is
        # still airborne is destroyed instead of capturing/landing.
        for motion in list(arbiter.active_motions()):
            if motion.arrival_time > clock_ms:
                continue

            entry = self._airborne_entry_at(motion.destination)
            if entry is None or entry.piece.color == motion.piece.color:
                continue
            if not (entry.start_time <= motion.arrival_time < entry.land_time):
                continue

            arbiter.cancel_motion(motion)
            board.remove_piece(motion.piece.cell)
            motion.piece.state = PieceState.CAPTURED
            events.append(
                InterceptionEvent(
                    attacker=motion.piece,
                    defender=entry.piece,
                    cell=entry.piece.cell,
                    king_captured=motion.piece.kind == PieceKind.KING,
                )
            )

        # Trigger 2: the jump's own duration elapses with an
        # already-in-flight attacker still pending (caught here even
        # though its own arrival is much later).
        for piece_id, entry in list(self._airborne.items()):
            if entry.land_time > clock_ms:
                continue

            attacking_motion = next(
                (
                    motion
                    for motion in arbiter.active_motions()
                    if motion.destination == entry.piece.cell
                    and motion.piece.color != entry.piece.color
                    and motion.start_time >= entry.start_time
                ),
                None,
            )

            if attacking_motion is not None:
                arbiter.cancel_motion(attacking_motion)
                board.remove_piece(attacking_motion.piece.cell)
                attacking_motion.piece.state = PieceState.CAPTURED
                events.append(
                    InterceptionEvent(
                        attacker=attacking_motion.piece,
                        defender=entry.piece,
                        cell=entry.piece.cell,
                        king_captured=attacking_motion.piece.kind == PieceKind.KING,
                    )
                )

            # land_time, not clock_ms: reflects the piece's actual scheduled
            # landing instant, avoiding cooldown inflation when resolve_due
            # is reached late via a large wait().
            entry.piece.available_at_ms = entry.land_time + JUMP_COOLDOWN_MS
            landings.append(JumpLandingEvent(piece=entry.piece, cell=entry.piece.cell))
            del self._airborne[piece_id]

        return events, landings
