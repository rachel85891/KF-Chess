"""Promotion as an optional extra, per spec.md §2: a pawn arriving on
its color's back rank promotes to Queen. Sourced from the legacy
kungfu_chess/services/promotion_service.py's event-driven design, but
simplified: that service had to construct an entirely new Piece since
the legacy Piece was frozen; kungfu_chess.model.piece.Piece is mutable,
so promoting is just reassigning .kind in place.

Applied as a post-processing step over the ArrivalEvents a core
GameEngine.wait() already returned - never hooks into
engine/game_engine.py itself.
"""

from __future__ import annotations

from typing import List

from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece, PieceKind
from kungfu_chess.realtime.motion import ArrivalEvent


def promotion_row(color: Color, board_height: int) -> int:
    if color == Color.WHITE:
        return 0
    return board_height - 1


def apply_promotions(board: Board, arrival_events: List[ArrivalEvent]) -> List[Piece]:
    promoted: List[Piece] = []

    for event in arrival_events:
        piece = event.piece
        if piece.kind is not PieceKind.PAWN:
            continue
        if event.destination.row != promotion_row(piece.color, board.height):
            continue

        piece.kind = PieceKind.QUEEN
        promoted.append(piece)

    return promoted
