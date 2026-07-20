"""Unit tests for kungfu_chess/notation/move_command_format.py - the
reverse of server/move_command.py's parser: given a color, piece kind,
and two Positions, produce the exact "WQe2e5"-style string the
server's own parse_move_command already accepts. Pure, no networking/
GameSession/server knowledge - lives in the shared kungfu_chess/
package specifically so a future client can format outgoing commands
without ever importing from server/ (see algebraic_notation.py's own
docstring for the full "why not server/" reasoning, which applies
identically here).
"""

from __future__ import annotations

from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.notation.move_command_format import format_move_command


def test_formats_a_white_queen_move_matching_the_servers_own_documented_example():
    text = format_move_command(
        color=Color.WHITE, piece_kind=PieceKind.QUEEN, from_cell=Position(row=6, col=4), to_cell=Position(row=3, col=4)
    )

    assert text == "WQe2e5"


def test_formats_a_black_pawn_move():
    text = format_move_command(
        color=Color.BLACK, piece_kind=PieceKind.PAWN, from_cell=Position(row=1, col=4), to_cell=Position(row=3, col=4)
    )

    assert text == "BPe7e5"


def test_formats_every_piece_kind_with_its_own_correct_letter():
    expected_letters = {
        PieceKind.KING: "K",
        PieceKind.QUEEN: "Q",
        PieceKind.ROOK: "R",
        PieceKind.BISHOP: "B",
        PieceKind.KNIGHT: "N",
        PieceKind.PAWN: "P",
    }

    for kind, letter in expected_letters.items():
        text = format_move_command(
            color=Color.WHITE, piece_kind=kind, from_cell=Position(row=7, col=0), to_cell=Position(row=7, col=1)
        )
        assert text[1] == letter
