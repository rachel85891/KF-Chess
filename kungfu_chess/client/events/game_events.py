"""Client-layer event types, per client_spec.md §6.

Frozen, read-only dataclasses published by GameEventPublisher. They
carry piece_id (Piece.id, kungfu_chess/model/piece.py) rather than a
Piece reference itself, so that Observers (MovesLogObserver,
ScoreObserver, PieceAnimator) never touch mutable model state directly
- only GameEventPublisher, on the model side, ever reads a Piece.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position


@dataclass(frozen=True)
class MoveRequested:
    """A move was requested, before GameEngine has validated it."""

    from_cell: Position
    to_cell: Position
    piece_id: int


@dataclass(frozen=True)
class MoveAccepted:
    """GameEngine accepted a move and started a motion for piece_id."""

    piece_id: int
    from_cell: Position
    to_cell: Position
    duration_ms: int


@dataclass(frozen=True)
class JumpAccepted:
    """ExtraEngine accepted a JUMP for piece_id.

    Source: extra/jump.py's JumpTracker via ExtraEngine, kept separate
    from MoveAccepted per client_spec.md §5 - jump is not a core-engine
    motion, and must reflect its real source, not be inferred visually.
    """

    piece_id: int
    from_cell: Position
    to_cell: Position
    duration_ms: int


@dataclass(frozen=True)
class MoveRejected:
    """GameEngine rejected a requested move; reason is its real reason
    string (e.g. "motion_in_progress", "cooldown_active", a RuleEngine
    validation reason), never invented here."""

    reason: str


@dataclass(frozen=True)
class PieceArrived:
    """A motion resolved: piece_id arrived at cell, optionally
    capturing captured_piece_id (None if the cell was empty)."""

    piece_id: int
    cell: Position
    captured_piece_id: Optional[int]


@dataclass(frozen=True)
class JumpLanded:
    """A JUMP's airborne period ended and its post-landing cooldown
    starts now: piece_id landed back at cell - always the piece's own
    cell, since JUMP never moves it (extra/jump.py's JumpTracker never
    creates a Motion for an airborne piece at all).

    A NEW, distinct event type, not a reused PieceArrived, even though
    both nominally carry "a piece, a cell": PieceArrived's third field,
    captured_piece_id, means "the piece that just arrived captured
    whoever already occupied its destination" - a relationship that
    does not exist for a jump landing. A jump's own interception
    mechanic (extra/jump.py's InterceptionEvent, published as its own
    AttackerIntercepted client event - see that dataclass's own
    docstring) destroys the ATTACKER trying to land on the airborne
    piece, never a piece the defender itself displaces; the defender's
    own landing never captures anything. Reusing PieceArrived (always with captured_piece_id=None)
    would also silently feed every existing PieceArrived consumer a
    payload shaped like a genuine arrival it structurally is not:
    SoundManager would treat it as a plain "move" echo, PieceAnimator's
    documented PieceArrived-forces-IDLE bugfix would force an unrelated
    animation transition, and the network wire format/reconciliation
    layer (kungfu_chess/notation/game_event_wire_format.py,
    kungfu_chess/client/loop/network_game_loop_runner.py) would need to
    treat a same-cell "arrival" as a special case it was never designed
    for. A new, narrow type lets CooldownTracker react to jump landings
    (client_spec.md §10's documented gap) without any of those
    consumers needing to change or accidentally misfire - OCP's
    "match on the one relevant type, ignore the rest" pattern this
    codebase already follows for every Observer."""

    piece_id: int
    cell: Position


@dataclass(frozen=True)
class AttackerIntercepted:
    """A jump's own interception mechanic (extra/jump.py's
    InterceptionEvent, resolved inside JumpTracker.resolve_due) has
    destroyed piece_id (the attacker) - it is GONE from the board, not
    merely idle or captured-by-arrival. Closes the gap JumpLanded's own
    docstring already flagged: "InterceptionEvent, not yet published as
    a client event."

    piece_id is the ATTACKER's own id - deliberately the primary
    subject field here (unlike PieceArrived, where piece_id names the
    piece that arrived and a SEPARATE captured_piece_id names whatever
    it displaced): an interception has no "arriving piece" at all, the
    attacker's own motion is cancelled, never completed, so the
    destroyed piece IS the one and only thing this event is about.

    cell reuses InterceptionEvent's own `cell` field verbatim (per this
    fix's own requirement to reuse that shape's information, not
    re-derive it) - the INTERCEPTION's own location (the defender's
    airborne cell the attacker was trying to reach), not necessarily
    the attacker's own last board position: an attacker intercepted via
    jump.py's Trigger 1 (its own motion resolving while the target is
    still airborne) is destroyed at its OWN source cell, having never
    actually reached `cell` - a consumer that needs to remove the
    attacker from a live Board must look up its own currently-tracked
    position by piece_id (Piece.cell), never assume it equals `cell`.
    Kept as informational context (matches jump.py's own naming/shape),
    not a removal target.

    defender_piece_id names the surviving piece whose jump caused this
    - included as useful, zero-cost context (mirrors PieceArrived's own
    captured_piece_id precedent: a secondary fact about the same
    moment). Unlike captured_piece_id, this is never Optional: an
    interception cannot happen without a real, airborne defender."""

    piece_id: int
    cell: Position
    defender_piece_id: int


@dataclass(frozen=True)
class GameOver:
    """The game ended; winner_color is the side whose king was NOT
    captured."""

    winner_color: Color


@dataclass(frozen=True)
class PromotionEvent:
    """A pawn (piece_id) arrived on its color's back rank and was
    promoted to new_kind, per extra/promotion.py's apply_promotions
    (Stage 14 - previously computed but never published, see
    GameEventPublisher.wait()'s own docstring for why). Always
    published alongside a PieceArrived for the same arrival - a
    promotion cannot happen without the arrival that triggers it, so
    this is deliberately a second, separate event rather than a field
    added onto PieceArrived (matching CaptureLogEntry's own precedent,
    kungfu_chess/client/events/observers.py: a materially different
    fact about the same moment is a second event, not an optional
    field that most PieceArrived events would never set). new_kind is
    apply_promotions's own real, current result (always QUEEN today,
    per spec.md §2), not hardcoded here - if promotion rules ever
    allow choosing a piece kind, this event's shape already
    accommodates it with no change needed."""

    piece_id: int
    cell: Position
    new_kind: PieceKind
