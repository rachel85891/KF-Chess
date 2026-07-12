"""BoardParser: text -> Board, per spec.md §13 (board notation) and
§15 (Text I/O adapters). Pure encode/decode - no movement rules,
command execution, or rendering.

Mirrors the validation order and error-code contract of
kungfu_chess.infrastructure.codecs.text_board_codec.TextBoardCodec
(EMPTY_BOARD -> ROW_WIDTH_MISMATCH -> UNKNOWN_TOKEN), rewritten fresh
against model types rather than reused directly: the old codec is
built around PieceTypeRegistry/domain.Piece, machinery this layer
doesn't need. kungfu_chess.model.piece.PieceKind's value is already
the board-notation letter (PieceKind.ROOK.value == "R"), so
PieceKind(letter) replaces the old registry lookup entirely.

The three error-code strings themselves are the external stdout
contract this parser must not diverge from - they lived in
kungfu_chess.config.errors while the legacy codec was still around
(now retired); with this the single remaining consumer, they're
declared directly here rather than in a separate single-consumer
module.
"""

from __future__ import annotations

from typing import Optional

from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece, PieceKind
from kungfu_chess.model.position import Position

ERR_EMPTY_BOARD = "EMPTY_BOARD"
ERR_ROW_WIDTH_MISMATCH = "ROW_WIDTH_MISMATCH"
ERR_UNKNOWN_TOKEN = "UNKNOWN_TOKEN"

_EMPTY_TOKEN = "."
_VALID_LETTERS = frozenset(kind.value for kind in PieceKind)
_VALID_COLORS = frozenset(color.value for color in Color)


class BoardParser:
    def parse(self, lines: list[str]) -> tuple[Optional[Board], Optional[str]]:
        rows_of_tokens = [line.split() for line in lines]

        error = self._validate(rows_of_tokens)
        if error is not None:
            return None, error

        grid = [
            [self._token_to_piece(token, row, col) for col, token in enumerate(row_tokens)]
            for row, row_tokens in enumerate(rows_of_tokens)
        ]
        return Board(grid), None

    def _validate(self, rows_of_tokens: list[list[str]]) -> Optional[str]:
        if not rows_of_tokens:
            return ERR_EMPTY_BOARD

        width = len(rows_of_tokens[0])
        for row in rows_of_tokens:
            if len(row) != width:
                return ERR_ROW_WIDTH_MISMATCH

        for row in rows_of_tokens:
            for token in row:
                if not self._is_valid_token(token):
                    return ERR_UNKNOWN_TOKEN

        return None

    def _is_valid_token(self, token: str) -> bool:
        if token == _EMPTY_TOKEN:
            return True
        return len(token) == 2 and token[0] in _VALID_COLORS and token[1] in _VALID_LETTERS

    def _token_to_piece(self, token: str, row: int, col: int) -> Optional[Piece]:
        if token == _EMPTY_TOKEN:
            return None
        return Piece(color=Color(token[0]), kind=PieceKind(token[1]), cell=Position(row=row, col=col))
