"""Unit tests for kungfu_chess/notation/jump_command_format.py - the
reverse of jump_command.py's parser: given a color, piece kind, and one
Position, produce the exact "JWRe2"-style string parse_jump_command
already accepts. Mirrors tests/unit/notation/test_move_command_format.py's
own structure, plus a round-trip section (format -> parse -> equal)
at the bottom - both format_jump_command and parse_jump_command live in
kungfu_chess/notation/ (unlike move's server/kungfu_chess split), so
this round-trip needs no server/ import at all and can live in the
same file as the formatter's own tests, rather than a separate
tests/unit/server/ file the way
tests/unit/server/test_move_command_format_roundtrip.py needed.
"""

from __future__ import annotations

import pytest

from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.notation.jump_command import ParsedJumpCommand, parse_jump_command
from kungfu_chess.notation.jump_command_format import format_jump_command


def test_formats_a_white_rook_jump():
    text = format_jump_command(color=Color.WHITE, piece_kind=PieceKind.ROOK, cell=Position(row=6, col=4))

    assert text == "JWRe2"


def test_formats_a_black_pawn_jump():
    text = format_jump_command(color=Color.BLACK, piece_kind=PieceKind.PAWN, cell=Position(row=1, col=4))

    assert text == "JBPe7"


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
        text = format_jump_command(color=Color.WHITE, piece_kind=kind, cell=Position(row=7, col=0))
        assert text[2] == letter


_ROUND_TRIP_CASES = [
    (Color.WHITE, PieceKind.ROOK, Position(row=6, col=4)),
    (Color.BLACK, PieceKind.PAWN, Position(row=1, col=4)),
    (Color.WHITE, PieceKind.KNIGHT, Position(row=7, col=1)),
]


@pytest.mark.parametrize("color,piece_kind,cell", _ROUND_TRIP_CASES)
def test_format_then_parse_round_trips_to_the_same_parsed_command(color, piece_kind, cell):
    text = format_jump_command(color=color, piece_kind=piece_kind, cell=cell)

    parsed = parse_jump_command(text)

    assert parsed == ParsedJumpCommand(color=color, piece_kind=piece_kind, cell=cell)
