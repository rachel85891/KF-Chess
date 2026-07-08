"""Domain events published to the EventBus when something happens to a
piece. Services react to these instead of being called directly, so a
custom game can register extra reactors (e.g. an alternate win
condition) without editing MoveResolver.
"""

from dataclasses import dataclass

from kungfu_chess.domain.piece import Piece

Cell = tuple[int, int]


@dataclass(frozen=True)
class PieceMoved:
    from_cell: Cell
    to_cell: Cell
    piece: Piece


@dataclass(frozen=True)
class PieceCaptured:
    cell: Cell
    captured_piece: Piece
    capturing_piece: Piece


@dataclass(frozen=True)
class PiecePromoted:
    cell: Cell
    from_piece: Piece
    to_piece: Piece


@dataclass(frozen=True)
class PieceIntercepted:
    origin_cell: Cell
    attacker_piece: Piece
    defender_cell: Cell


@dataclass(frozen=True)
class GameEnded:
    reason: str
