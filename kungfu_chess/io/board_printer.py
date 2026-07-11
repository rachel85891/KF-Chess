"""BoardPrinter: Board -> text, the exact inverse of BoardParser's
encoding, per spec.md §13/§15. Pure encode - no board mutation, no
input parsing, no test-assertion logic beyond text comparison.
"""

from __future__ import annotations

from typing import Optional

from kungfu_chess.model.board import Board
from kungfu_chess.model.piece import Piece
from kungfu_chess.model.position import Position

_EMPTY_TOKEN = "."


class BoardPrinter:
    def print(self, board: Board) -> str:
        lines = []
        for row in range(board.height):
            tokens = [self._piece_to_token(board.piece_at(Position(row=row, col=col))) for col in range(board.width)]
            lines.append(" ".join(tokens))
        return "\n".join(lines)

    def _piece_to_token(self, piece: Optional[Piece]) -> str:
        if piece is None:
            return _EMPTY_TOKEN
        return piece.color.value + piece.kind.value
