"""Per-piece-type movement rules, per spec.md §6: legal_destination(board,
piece) -> set[Position] for each of Rook, Bishop, Queen, Knight, King, Pawn.

Reuse, not rewrite: the shape/geometry checks (is_rook_move, etc.) and
the intervening-cell walk (path_cells) live in rules/shapes.py (moved
there from the retired domain/movement/{rules,path}.py - originally
reused read-only from the domain layer, now relocated into this
package since this is their only remaining consumer), are pure
functions with zero coupling to Piece/Board (plain ints/Color in,
bool/cells out), and are already exercised by many passing tests.
Reimplementing them here would risk silently diverging from
proven-correct geometry for no benefit, so each class below delegates
to the matching shapes function rather than re-deriving the shape
logic. Only the model-layer plumbing (walking every board cell,
translating Position/Piece into the (dr, dc, color, is_capture,
is_start_row) shape these functions expect, and applying the resulting
set) is new.

legal_destination itself is defined once, on the PieceRules base
class, as a template method: it enumerates every cell on the board and
defers exactly two decisions to each subclass - the shape check
(_is_legal_shape) and whether a clear path is required
(_requires_clear_path, default False). This keeps the O(rows*cols)
enumeration and the sliding-piece stop-before-friendly /
capture-enemy-but-not-past-it logic defined exactly once, while still
giving each piece type its own small Strategy class per spec.md §3's
pattern vocabulary ("PieceRules - Strategy per piece type"). Classes
are stateless and take no constructor arguments.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece
from kungfu_chess.model.position import Position
from kungfu_chess.rules.shapes import (
    is_bishop_move,
    is_king_move,
    is_knight_move,
    is_pawn_move,
    is_queen_move,
    is_rook_move,
    path_cells,
)


def _path_is_blocked(board: Board, source: Position, destination: Position) -> bool:
    return any(
        board.piece_at(Position(row=row, col=col)) is not None
        for row, col in path_cells(source.row, source.col, destination.row, destination.col)
    )


def _pawn_start_row(board: Board, color: Color) -> int:
    """The row a color's pawns begin on: one row in from each color's
    back edge (board.height - 2 for white, 1 for black) - matching
    standard chess, where pawns start on the second rank, not the back
    rank shared with the rest of the back-row pieces.

    This was previously board.height - 1 / 0 (the literal back edge),
    a bug inherited from the legacy
    services/move_legality_service.py's identical helper and carried
    over unnoticed during the PieceRules reuse decision - confirmed
    wrong by the external bootcamp platform's pawn double-step test
    cases. Computed unconditionally (not just for pawns) since every
    other _is_legal_shape ignores is_start_row, so gating this on
    piece kind would add a branch with no behavioral effect."""
    if color == Color.WHITE:
        return board.height - 2
    return 1


class PieceRules(ABC):
    @abstractmethod
    def _is_legal_shape(self, dr: int, dc: int, color: Color, is_capture: bool, is_start_row: bool) -> bool:
        raise NotImplementedError

    def _requires_clear_path(self, dr: int, dc: int) -> bool:
        return False

    def legal_destination(self, board: Board, piece: Piece) -> set[Position]:
        destinations: set[Position] = set()
        is_start_row = piece.cell.row == _pawn_start_row(board, piece.color)

        for row in range(board.height):
            for col in range(board.width):
                candidate = Position(row=row, col=col)
                target = board.piece_at(candidate)
                if target is not None and target.color == piece.color:
                    continue

                dr = candidate.row - piece.cell.row
                dc = candidate.col - piece.cell.col
                is_capture = target is not None

                if not self._is_legal_shape(dr, dc, piece.color, is_capture, is_start_row):
                    continue
                if self._requires_clear_path(dr, dc) and _path_is_blocked(board, piece.cell, candidate):
                    continue

                destinations.add(candidate)

        return destinations


class RookRules(PieceRules):
    def _is_legal_shape(self, dr: int, dc: int, color: Color, is_capture: bool, is_start_row: bool) -> bool:
        return is_rook_move(dr, dc, color, is_capture, is_start_row)

    def _requires_clear_path(self, dr: int, dc: int) -> bool:
        return True


class BishopRules(PieceRules):
    def _is_legal_shape(self, dr: int, dc: int, color: Color, is_capture: bool, is_start_row: bool) -> bool:
        return is_bishop_move(dr, dc, color, is_capture, is_start_row)

    def _requires_clear_path(self, dr: int, dc: int) -> bool:
        return True


class QueenRules(PieceRules):
    def _is_legal_shape(self, dr: int, dc: int, color: Color, is_capture: bool, is_start_row: bool) -> bool:
        return is_queen_move(dr, dc, color, is_capture, is_start_row)

    def _requires_clear_path(self, dr: int, dc: int) -> bool:
        return True


class KnightRules(PieceRules):
    def _is_legal_shape(self, dr: int, dc: int, color: Color, is_capture: bool, is_start_row: bool) -> bool:
        return is_knight_move(dr, dc, color, is_capture, is_start_row)


class KingRules(PieceRules):
    def _is_legal_shape(self, dr: int, dc: int, color: Color, is_capture: bool, is_start_row: bool) -> bool:
        return is_king_move(dr, dc, color, is_capture, is_start_row)


class PawnRules(PieceRules):
    def _is_legal_shape(self, dr: int, dc: int, color: Color, is_capture: bool, is_start_row: bool) -> bool:
        return is_pawn_move(dr, dc, color, is_capture, is_start_row)

    def _requires_clear_path(self, dr: int, dc: int) -> bool:
        return abs(dr) == 2
