from __future__ import annotations

from kungfu_chess.config.errors import ERR_EMPTY_BOARD, ERR_ROW_WIDTH_MISMATCH, ERR_UNKNOWN_TOKEN
from kungfu_chess.domain.color import Color
from kungfu_chess.io.board_parser import BoardParser
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position


def test_parses_rectangular_board_with_dimensions_inferred():
    lines = [". . .", ". . ."]

    board, error = BoardParser().parse(lines)

    assert error is None
    assert board.height == 2
    assert board.width == 3


def test_parses_piece_tokens_with_correct_color_and_kind():
    lines = ["wK bQ", ". ."]

    board, error = BoardParser().parse(lines)

    assert error is None
    king = board.piece_at(Position(row=0, col=0))
    queen = board.piece_at(Position(row=0, col=1))
    assert king.color is Color.WHITE
    assert king.kind is PieceKind.KING
    assert queen.color is Color.BLACK
    assert queen.kind is PieceKind.QUEEN


def test_dot_parses_as_empty_cell():
    lines = [". wP", "bR ."]

    board, error = BoardParser().parse(lines)

    assert error is None
    assert board.piece_at(Position(row=0, col=0)) is None
    assert board.piece_at(Position(row=1, col=1)) is None


def test_rejects_unknown_token():
    lines = ["wK wX", ". ."]

    board, error = BoardParser().parse(lines)

    assert board is None
    assert error == ERR_UNKNOWN_TOKEN


def test_rejects_mismatched_row_widths():
    lines = [". . .", ". ."]

    board, error = BoardParser().parse(lines)

    assert board is None
    assert error == ERR_ROW_WIDTH_MISMATCH


def test_rejects_empty_board():
    board, error = BoardParser().parse([])

    assert board is None
    assert error == ERR_EMPTY_BOARD
