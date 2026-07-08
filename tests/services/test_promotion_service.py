from kungfu_chess.config.piece_registry import PieceTypeRegistry
from kungfu_chess.domain.board import Board
from kungfu_chess.domain.color import Color
from kungfu_chess.domain.events import PieceMoved, PiecePromoted
from kungfu_chess.domain.piece import Piece
from kungfu_chess.services.event_bus import EventBus
from kungfu_chess.services.promotion_service import PromotionService

REGISTRY = PieceTypeRegistry.standard_chess()


def _piece(letter, color):
    return Piece(color=color, piece_type=REGISTRY.get(letter))


def test_white_pawn_promotes_to_queen_on_row_zero():
    board = Board.from_grid([[None], [None], [None]])
    bus = EventBus()
    PromotionService(board, bus)
    pawn = _piece("P", Color.WHITE)
    board.set_piece(0, 0, pawn)

    bus.publish(PieceMoved(from_cell=(2, 0), to_cell=(0, 0), piece=pawn))

    promoted = board.get_piece(0, 0)
    assert promoted.letter == "Q"
    assert promoted.color == Color.WHITE


def test_black_pawn_promotes_on_the_boards_last_row_not_row_zero():
    board = Board.from_grid([[None], [None], [None]])
    bus = EventBus()
    PromotionService(board, bus)
    pawn = _piece("P", Color.BLACK)
    board.set_piece(2, 0, pawn)

    bus.publish(PieceMoved(from_cell=(0, 0), to_cell=(2, 0), piece=pawn))

    assert board.get_piece(2, 0).letter == "Q"


def test_no_promotion_off_the_promotion_row():
    board = Board.from_grid([[None], [None], [None]])
    bus = EventBus()
    PromotionService(board, bus)
    pawn = _piece("P", Color.WHITE)
    board.set_piece(1, 0, pawn)

    bus.publish(PieceMoved(from_cell=(2, 0), to_cell=(1, 0), piece=pawn))

    assert board.get_piece(1, 0) is pawn


def test_non_promotable_piece_type_is_left_alone_on_promotion_row():
    board = Board.from_grid([[None]])
    bus = EventBus()
    PromotionService(board, bus)
    rook = _piece("R", Color.WHITE)
    board.set_piece(0, 0, rook)

    bus.publish(PieceMoved(from_cell=(1, 0), to_cell=(0, 0), piece=rook))

    assert board.get_piece(0, 0) is rook


def test_promotion_publishes_piece_promoted_event():
    board = Board.from_grid([[None]])
    bus = EventBus()
    PromotionService(board, bus)
    received = []
    bus.subscribe(PiecePromoted, received.append)
    pawn = _piece("P", Color.WHITE)
    board.set_piece(0, 0, pawn)

    bus.publish(PieceMoved(from_cell=(1, 0), to_cell=(0, 0), piece=pawn))

    assert len(received) == 1
    assert received[0].to_piece.letter == "Q"
