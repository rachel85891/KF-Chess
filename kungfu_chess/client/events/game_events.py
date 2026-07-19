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
