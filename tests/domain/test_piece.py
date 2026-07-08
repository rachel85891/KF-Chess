from kungfu_chess.domain.color import Color
from kungfu_chess.domain.piece import Piece, PieceType


def _always_legal(dr, dc, color, is_capture, is_start_row):
    return True


def _never_needs_path_check(dr, dc):
    return False


def test_piece_exposes_letter_and_royal_via_piece_type():
    king_type = PieceType(
        letter="K", name="King", movement_rule=_always_legal, requires_clear_path=_never_needs_path_check, is_royal=True
    )
    piece = Piece(color=Color.WHITE, piece_type=king_type)

    assert piece.letter == "K"
    assert piece.is_royal is True
    assert piece.color is Color.WHITE


def test_piece_type_promotion_chain():
    queen_type = PieceType(letter="Q", name="Queen", movement_rule=_always_legal, requires_clear_path=_never_needs_path_check)
    pawn_type = PieceType(
        letter="P",
        name="Pawn",
        movement_rule=_always_legal,
        requires_clear_path=_never_needs_path_check,
        promotes_to=queen_type,
    )

    assert pawn_type.promotes_to is queen_type
    assert queen_type.promotes_to is None


def test_pieces_are_value_objects_equal_by_value():
    pawn_type_a = PieceType(letter="P", name="Pawn", movement_rule=_always_legal, requires_clear_path=_never_needs_path_check)
    pawn_type_b = PieceType(letter="P", name="Pawn", movement_rule=_always_legal, requires_clear_path=_never_needs_path_check)

    piece_a = Piece(color=Color.BLACK, piece_type=pawn_type_a)
    piece_b = Piece(color=Color.BLACK, piece_type=pawn_type_b)

    assert piece_a == piece_b
