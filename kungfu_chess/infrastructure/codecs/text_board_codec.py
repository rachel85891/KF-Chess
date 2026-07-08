"""TextBoardCodec: the original stdin/stdout board format - 'wK'/'.'
style tokens, one row per line, cells space-separated.

Token validity is a plain membership check against the injected
registry's precomputed valid_tokens set - this codec never combines a
color check with a letter check itself, and never hardcodes which
letters or color prefixes exist.
"""

from typing import Optional

from kungfu_chess.config.errors import ERR_EMPTY_BOARD, ERR_ROW_WIDTH_MISMATCH, ERR_UNKNOWN_TOKEN
from kungfu_chess.config.piece_registry import PieceTypeRegistry
from kungfu_chess.domain.board import Board
from kungfu_chess.domain.color import Color
from kungfu_chess.domain.piece import Piece
from kungfu_chess.infrastructure.codecs.board_codec import BoardCodec

_EMPTY_TOKEN = "."


class TextBoardCodec(BoardCodec):
    def decode(self, lines: list[str], registry: PieceTypeRegistry) -> tuple[Optional[Board], Optional[str]]:
        rows_of_tokens = [line.split() for line in lines]

        error = self._validate(rows_of_tokens, registry)
        if error is not None:
            return None, error

        grid = [[self._token_to_piece(token, registry) for token in row] for row in rows_of_tokens]
        return Board.from_grid(grid), None

    def encode(self, board: Board) -> str:
        lines = []
        for row in range(board.num_rows):
            tokens = [self._piece_to_token(board.get_piece(row, col)) for col in range(board.num_cols)]
            lines.append(" ".join(tokens))
        return "\n".join(lines)

    def _validate(self, rows_of_tokens: list[list[str]], registry: PieceTypeRegistry) -> Optional[str]:
        if not rows_of_tokens:
            return ERR_EMPTY_BOARD

        width = len(rows_of_tokens[0])
        for row in rows_of_tokens:
            if len(row) != width:
                return ERR_ROW_WIDTH_MISMATCH

        for row in rows_of_tokens:
            for token in row:
                if not self._is_valid_token(token, registry):
                    return ERR_UNKNOWN_TOKEN

        return None

    def _is_valid_token(self, token: str, registry: PieceTypeRegistry) -> bool:
        return token == _EMPTY_TOKEN or token in registry.valid_tokens

    def _token_to_piece(self, token: str, registry: PieceTypeRegistry) -> Optional[Piece]:
        if token == _EMPTY_TOKEN:
            return None
        return Piece(color=Color(token[0]), piece_type=registry.get(token[1]))

    def _piece_to_token(self, piece: Optional[Piece]) -> str:
        if piece is None:
            return _EMPTY_TOKEN
        return piece.color.value + piece.letter
