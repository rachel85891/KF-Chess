"""BoardPrinter: Board -> text, the exact inverse of BoardParser's
encoding, per spec.md §13/§15. Pure encode - no board mutation, no
input parsing, no test-assertion logic beyond text comparison.

STAGE G4 - piece_to_token IS NOW PUBLIC: server/presentation/
protocol_handler.py's own BOARD_DELTA formatting needs the exact same
per-cell "color letter + kind letter" (or "." for empty) token this
class already produces for a full board - reusing this method directly
rather than re-inventing a second color/kind-letter mapping (see that
module's own "STAGE G4" docstring section). Renamed from the previous
`_piece_to_token` (never called from outside this module before this
stage - re-verified directly via a repo-wide grep before renaming).
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
            tokens = [self.piece_to_token(board.piece_at(Position(row=row, col=col))) for col in range(board.width)]
            lines.append(" ".join(tokens))
        return "\n".join(lines)

    def piece_to_token(self, piece: Optional[Piece]) -> str:
        """The exact 2-character (or "." for empty) wire token for one
        cell's occupant - public so other wire-format code (e.g.
        BOARD_DELTA's own per-cell formatting) can reuse this single
        color/kind-letter mapping rather than re-deriving it."""

        if piece is None:
            return _EMPTY_TOKEN
        return piece.color.value + piece.kind.value
