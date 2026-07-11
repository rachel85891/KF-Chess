from __future__ import annotations

from kungfu_chess.domain.color import Color
from kungfu_chess.io.board_parser import BoardParser
from kungfu_chess.io.board_printer import BoardPrinter
from kungfu_chess.model.board import Board
from kungfu_chess.model.piece import Piece, PieceKind
from kungfu_chess.model.position import Position


def test_printer_output_matches_space_separated_dot_format():
    grid = [
        [Piece(color=Color.WHITE, kind=PieceKind.KING, cell=Position(row=0, col=0)), None],
        [None, Piece(color=Color.BLACK, kind=PieceKind.PAWN, cell=Position(row=1, col=1))],
    ]
    board = Board(grid)

    text = BoardPrinter().print(board)

    assert text == "wK .\n. bP"


def test_round_trip_print_parse_print_is_stable():
    text = "wK . bQ\n. bN .\nwP . ."

    board, error = BoardParser().parse(text.splitlines())
    assert error is None
    first_print = BoardPrinter().print(board)

    reparsed_board, reparsed_error = BoardParser().parse(first_print.splitlines())
    assert reparsed_error is None
    second_print = BoardPrinter().print(reparsed_board)

    assert first_print == second_print
