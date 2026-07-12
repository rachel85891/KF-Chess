from __future__ import annotations

import pytest

from kungfu_chess.texttests.script_parser import CommandKind, ScriptParser


def test_parses_click_command():
    command = ScriptParser().parse_line("click 150 250")

    assert command.kind is CommandKind.CLICK
    assert command.x == 150
    assert command.y == 250


def test_parses_wait_command():
    command = ScriptParser().parse_line("wait 1000")

    assert command.kind is CommandKind.WAIT
    assert command.ms == 1000


def test_parses_print_board_command():
    command = ScriptParser().parse_line("print board")

    assert command.kind is CommandKind.PRINT_BOARD


@pytest.mark.parametrize("line", ["jump 50 50", "foo bar", "", "click 1", "click 1 2 3"])
def test_ignores_unrecognized_lines(line):
    assert ScriptParser().parse_line(line) is None
