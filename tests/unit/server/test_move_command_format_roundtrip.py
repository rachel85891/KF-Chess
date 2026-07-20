"""NEW test file (not an edit to any existing one) proving
kungfu_chess.notation.move_command_format.format_move_command and
server.move_command.parse_move_command compose correctly: formatting
a command and parsing it back reconstructs the exact same
ParsedMoveCommand. This lives under tests/unit/server/, not
tests/unit/notation/, specifically because it imports server.
move_command (the parser) - importing server/ from a test module is
fine (only production code under kungfu_chess/client/ must never do
so); keeping this cross-boundary check out of tests/unit/notation/
keeps that suite's own imports symmetric with what
kungfu_chess/notation/ itself is allowed to depend on.
"""

from __future__ import annotations

import pytest

from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.notation.move_command_format import format_move_command
from server.move_command import ParsedMoveCommand, parse_move_command

_CASES = [
    (Color.WHITE, PieceKind.QUEEN, Position(row=6, col=4), Position(row=3, col=4)),
    (Color.BLACK, PieceKind.PAWN, Position(row=1, col=4), Position(row=3, col=4)),
    (Color.WHITE, PieceKind.KNIGHT, Position(row=7, col=1), Position(row=5, col=2)),
]


@pytest.mark.parametrize("color,piece_kind,from_cell,to_cell", _CASES)
def test_format_then_parse_round_trips_to_the_same_parsed_command(color, piece_kind, from_cell, to_cell):
    text = format_move_command(color=color, piece_kind=piece_kind, from_cell=from_cell, to_cell=to_cell)

    parsed = parse_move_command(text)

    assert parsed == ParsedMoveCommand(color=color, piece_kind=piece_kind, from_cell=from_cell, to_cell=to_cell)
