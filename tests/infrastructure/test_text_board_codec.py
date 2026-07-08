from kungfu_chess.config.errors import ERR_EMPTY_BOARD, ERR_ROW_WIDTH_MISMATCH, ERR_UNKNOWN_TOKEN
from kungfu_chess.config.piece_registry import PieceTypeRegistry
from kungfu_chess.domain.color import Color
from kungfu_chess.infrastructure.codecs.text_board_codec import TextBoardCodec

REGISTRY = PieceTypeRegistry.standard_chess()
CODEC = TextBoardCodec()


def test_decode_empty_lines_is_empty_board_error():
    board, error = CODEC.decode([], REGISTRY)
    assert board is None
    assert error == ERR_EMPTY_BOARD


def test_decode_row_width_mismatch():
    board, error = CODEC.decode(["wK wQ", "wK"], REGISTRY)
    assert board is None
    assert error == ERR_ROW_WIDTH_MISMATCH


def test_decode_unknown_token():
    board, error = CODEC.decode(["wX"], REGISTRY)
    assert board is None
    assert error == ERR_UNKNOWN_TOKEN


def test_decode_valid_board_builds_pieces():
    board, error = CODEC.decode(["bK .", ". wR"], REGISTRY)
    assert error is None
    assert board.num_rows == 2
    assert board.num_cols == 2
    assert board.get_piece(0, 0).letter == "K"
    assert board.get_piece(0, 0).color == Color.BLACK
    assert board.get_piece(0, 1) is None
    assert board.get_piece(1, 1).letter == "R"
    assert board.get_piece(1, 1).color == Color.WHITE


def test_encode_round_trips_to_the_same_canonical_string():
    original = "bK . .\n. . wR\nwP wP wP"
    board, error = CODEC.decode(original.splitlines(), REGISTRY)
    assert error is None
    assert CODEC.encode(board) == original


def test_unknown_token_letter_not_in_registry_is_rejected_even_if_well_formed():
    board, error = CODEC.decode(["wZ"], REGISTRY)
    assert board is None
    assert error == ERR_UNKNOWN_TOKEN


def test_custom_registry_accepts_letters_standard_registry_would_reject():
    from kungfu_chess.domain.movement.rules import is_king_move
    from kungfu_chess.domain.piece import PieceType

    custom_registry = PieceTypeRegistry(
        {"Z": PieceType(letter="Z", name="Zeppelin", movement_rule=is_king_move, requires_clear_path=lambda dr, dc: False)}
    )

    board, error = CODEC.decode(["wZ"], custom_registry)
    assert error is None
    assert board.get_piece(0, 0).letter == "Z"
