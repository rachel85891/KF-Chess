"""Pure unit tests for kungfu_chess/notation/jump_command.py - the real
WS jump-command grammar this server understands: "J<W|B><K|Q|R|B|N|P>
<file><rank>", e.g. "JWRe2". No networking, no GameSession - this is a
pure parser, independently testable, mirroring
tests/unit/server/test_move_command.py's own structure exactly.
"""

from __future__ import annotations

import pytest

from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.notation.jump_command import MalformedJumpCommandError, ParsedJumpCommand, parse_jump_command


def test_parses_a_well_formed_white_rook_jump():
    parsed = parse_jump_command("JWRe2")

    assert parsed == ParsedJumpCommand(color=Color.WHITE, piece_kind=PieceKind.ROOK, cell=Position(row=6, col=4))


def test_parses_a_well_formed_black_pawn_jump():
    parsed = parse_jump_command("JBPe7")

    assert parsed == ParsedJumpCommand(color=Color.BLACK, piece_kind=PieceKind.PAWN, cell=Position(row=1, col=4))


def test_color_and_piece_letters_are_case_insensitive():
    assert parse_jump_command("jwre2") == parse_jump_command("JWRe2")


def test_wrong_length_raises_malformed_jump_command_error():
    with pytest.raises(MalformedJumpCommandError):
        parse_jump_command("JWRe2x")


def test_missing_leading_marker_raises_malformed_jump_command_error():
    # Same length (5) and otherwise-valid fields, but missing the
    # leading "J" marker - must still be rejected, not silently parsed
    # as if it were one character short of a move command.
    with pytest.raises(MalformedJumpCommandError):
        parse_jump_command("WRe2x")


def test_unknown_color_letter_raises_malformed_jump_command_error():
    with pytest.raises(MalformedJumpCommandError):
        parse_jump_command("JXRe2")


def test_unknown_piece_letter_raises_malformed_jump_command_error():
    with pytest.raises(MalformedJumpCommandError):
        parse_jump_command("JWXe2")


def test_invalid_square_raises_malformed_jump_command_error():
    with pytest.raises(MalformedJumpCommandError):
        parse_jump_command("JWRz9")


def test_empty_string_raises_malformed_jump_command_error():
    with pytest.raises(MalformedJumpCommandError):
        parse_jump_command("")
