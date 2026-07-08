"""PromotionService: reacts to a piece having moved and promotes it if
it landed on its color's promotion row. Entirely data-driven via
PieceType.promotes_to - a custom piece type that should never promote
simply leaves promotes_to as None, no engine code changes needed.

A class (not a free function) because it holds real collaborators: the
board it mutates and the event bus it both listens to and publishes on.
"""

from kungfu_chess.domain.board import Board
from kungfu_chess.domain.color import Color
from kungfu_chess.domain.events import PieceMoved, PiecePromoted
from kungfu_chess.domain.piece import Piece
from kungfu_chess.services.event_bus import EventBus


def _promotion_row(board: Board, color: Color) -> int:
    """The last row a piece of this color can advance to: row 0 for
    white (moving toward decreasing rows), the board's last row for
    black - the inverse of the pawn start row, not the same helper."""
    if color == Color.WHITE:
        return 0
    return board.num_rows - 1


class PromotionService:
    def __init__(self, board: Board, event_bus: EventBus):
        self._board = board
        self._event_bus = event_bus
        event_bus.subscribe(PieceMoved, self._on_piece_moved)

    def _on_piece_moved(self, event: PieceMoved) -> None:
        piece = event.piece
        promotes_to = piece.piece_type.promotes_to
        if promotes_to is None:
            return

        row, col = event.to_cell
        if row != _promotion_row(self._board, piece.color):
            return

        promoted = Piece(color=piece.color, piece_type=promotes_to)
        self._board.set_piece(row, col, promoted)
        self._event_bus.publish(PiecePromoted(cell=event.to_cell, from_piece=piece, to_piece=promoted))
