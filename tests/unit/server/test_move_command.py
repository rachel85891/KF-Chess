"""Pure unit tests for server/move_command.py - the real WS move-
command grammar this server understands (per the CTD26 slides):
"<W|B><K|Q|R|B|N|P><file><rank><file><rank>", e.g. "WQe2e5". No
networking, no GameSession, no ConnectionManager - this is a pure
parser, independently testable (per this stage's own SRP requirement).
"""

from __future__ import annotations

import pytest

from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position
from server.move_command import MalformedCommandError, ParsedMoveCommand, parse_move_command


def test_parses_a_well_formed_white_queen_move():
    parsed = parse_move_command("WQe2e5")

    assert parsed == ParsedMoveCommand(
        color=Color.WHITE,
        piece_kind=PieceKind.QUEEN,
        from_cell=Position(row=6, col=4),
        to_cell=Position(row=3, col=4),
    )


def test_parses_a_well_formed_black_pawn_move():
    parsed = parse_move_command("BPe7e5")

    assert parsed == ParsedMoveCommand(
        color=Color.BLACK,
        piece_kind=PieceKind.PAWN,
        from_cell=Position(row=1, col=4),
        to_cell=Position(row=3, col=4),
    )


def test_color_and_piece_letters_are_case_insensitive():
    assert parse_move_command("wqe2e5") == parse_move_command("WQe2e5")


def test_wrong_length_raises_malformed_command_error():
    with pytest.raises(MalformedCommandError):
        parse_move_command("WQe2e5x")


def test_unknown_color_letter_raises_malformed_command_error():
    with pytest.raises(MalformedCommandError):
        parse_move_command("XQe2e5")


def test_unknown_piece_letter_raises_malformed_command_error():
    with pytest.raises(MalformedCommandError):
        parse_move_command("WXe2e5")


def test_invalid_source_square_raises_malformed_command_error():
    with pytest.raises(MalformedCommandError):
        parse_move_command("WQz9e5")


def test_invalid_destination_square_raises_malformed_command_error():
    with pytest.raises(MalformedCommandError):
        parse_move_command("WQe2z9")


def test_empty_string_raises_malformed_command_error():
    with pytest.raises(MalformedCommandError):
        parse_move_command("")
