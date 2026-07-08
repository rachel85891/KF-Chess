from kungfu_chess.config.piece_registry import PieceTypeRegistry
from kungfu_chess.domain.color import Color
from kungfu_chess.domain.events import PieceCaptured
from kungfu_chess.domain.piece import Piece
from kungfu_chess.services.win_condition import RoyalCaptureWinCondition

REGISTRY = PieceTypeRegistry.standard_chess()


def _piece(letter, color):
    return Piece(color=color, piece_type=REGISTRY.get(letter))


def test_capturing_a_king_ends_the_game():
    condition = RoyalCaptureWinCondition()
    event = PieceCaptured(
        cell=(0, 0),
        captured_piece=_piece("K", Color.BLACK),
        capturing_piece=_piece("R", Color.WHITE),
    )
    assert condition.ends_game(event) is True


def test_capturing_a_non_royal_piece_does_not_end_the_game():
    condition = RoyalCaptureWinCondition()
    event = PieceCaptured(
        cell=(0, 0),
        captured_piece=_piece("P", Color.BLACK),
        capturing_piece=_piece("R", Color.WHITE),
    )
    assert condition.ends_game(event) is False
