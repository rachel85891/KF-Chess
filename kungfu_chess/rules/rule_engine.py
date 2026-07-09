"""RuleEngine: read-only move-legality validation, per spec.md §8.

Answers "is this move legal right now" without mutating anything - it
only ever calls board.in_bounds/board.piece_at (non-mutating reads)
and PieceRules.legal_destination, never
add_piece/move_piece/remove_piece.

The PieceKind -> PieceRules dispatch table lives here rather than in
piece_rules.py: piece_rules.py has no existing dependency on PieceKind
(each Strategy class stands alone), and deciding which strategy
applies to a given piece's kind is a RuleEngine-level concern, not a
PieceRules one. spec.md §4 doesn't call for a separate registry file
at this layer, so this stays a small dict next to its only consumer
rather than a new module.
"""

from __future__ import annotations

from dataclasses import dataclass

from kungfu_chess.model.board import Board
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.rules.piece_rules import (
    BishopRules,
    KingRules,
    KnightRules,
    PawnRules,
    PieceRules,
    QueenRules,
    RookRules,
)

_PIECE_RULES: dict[PieceKind, PieceRules] = {
    PieceKind.ROOK: RookRules(),
    PieceKind.BISHOP: BishopRules(),
    PieceKind.QUEEN: QueenRules(),
    PieceKind.KNIGHT: KnightRules(),
    PieceKind.KING: KingRules(),
    PieceKind.PAWN: PawnRules(),
}


@dataclass(frozen=True)
class MoveValidation:
    is_valid: bool
    reason: str


class RuleEngine:
    def validate_move(self, board: Board, from_cell: Position, to_cell: Position) -> MoveValidation:
        if not board.in_bounds(from_cell) or not board.in_bounds(to_cell):
            return MoveValidation(is_valid=False, reason="outside_board")

        piece = board.piece_at(from_cell)
        if piece is None:
            return MoveValidation(is_valid=False, reason="empty_source")

        target = board.piece_at(to_cell)
        if target is not None and target.color == piece.color:
            return MoveValidation(is_valid=False, reason="friendly_destination")

        piece_rules = _PIECE_RULES[piece.kind]
        if to_cell not in piece_rules.legal_destination(board, piece):
            return MoveValidation(is_valid=False, reason="illegal_piece_move")

        return MoveValidation(is_valid=True, reason="ok")
