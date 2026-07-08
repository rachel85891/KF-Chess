"""BoardCodec: Strategy interface for turning raw input into a Board and
back into output. TextBoardCodec is the only implementation today; a
future BinaryBoardCodec implements the same interface so nothing above
this layer (GameEngine, cli_runner) needs to change to support it.
"""

from abc import ABC, abstractmethod
from typing import Optional

from kungfu_chess.config.piece_registry import PieceTypeRegistry
from kungfu_chess.domain.board import Board


class BoardCodec(ABC):
    @abstractmethod
    def decode(self, lines: list[str], registry: PieceTypeRegistry) -> tuple[Optional[Board], Optional[str]]:
        """Returns (board, None) on success or (None, error_code) on failure."""
        raise NotImplementedError

    @abstractmethod
    def encode(self, board: Board) -> str:
        raise NotImplementedError
