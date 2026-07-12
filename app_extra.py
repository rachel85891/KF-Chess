"""Entry point for the OPTIONAL extras track (spec.md §2: JUMP and
Promotion) - reads a board fixture + commands from stdin, same
Board:/Commands: contract as app.py, but recognizes "jump <x> <y>" in
addition to the 3 core commands via ExtendedScriptParser.

Coexists with app.py (the core, spec-pure 4-command entry point) and
main.py (the legacy engine's entry point) - neither is touched here.
app.py continues to prove the core satisfies spec.md §13's "exactly 4
commands" on its own; this file is a clearly separate, obviously
optional/removable surface for the extras.

Reimplements its own small Board:/Commands: section-splitter rather
than importing texttests/script_runner.py's private _split_sections,
for the same reason ScriptRunner itself reimplemented cli_runner.py's
version: ~15 lines, trivial, and keeps this extras entry point
decoupled from texttests/ internals.
"""

from __future__ import annotations

import sys

from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.extra.extended_script_parser import ExtendedCommandKind, ExtendedScriptParser
from kungfu_chess.extra.extra_engine import ExtraEngine
from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.input.controller import Controller
from kungfu_chess.io.board_parser import BoardParser
from kungfu_chess.io.board_printer import BoardPrinter

_BOARD_HEADER = "Board:"
_COMMANDS_HEADER = "Commands:"


def _split_sections(lines: list[str]) -> tuple[list[str], list[str]]:
    board_lines: list[str] = []
    command_lines: list[str] = []
    section = None

    for line in lines:
        stripped = line.strip()
        if stripped == _BOARD_HEADER:
            section = "board"
            continue
        if stripped == _COMMANDS_HEADER:
            section = "commands"
            continue
        if not stripped:
            continue
        if section == "board":
            board_lines.append(stripped)
        elif section == "commands":
            command_lines.append(stripped)

    return board_lines, command_lines


def run_extra(lines: list[str]) -> None:
    board_lines, command_lines = _split_sections(lines)

    board, error = BoardParser().parse(board_lines)
    if error is not None:
        print(f"ERROR {error}")
        return

    engine = GameEngine(board)
    extra_engine = ExtraEngine(engine)
    controller = Controller(engine)
    board_mapper = BoardMapper()
    printer = BoardPrinter()
    parser = ExtendedScriptParser()

    for line in command_lines:
        command = parser.parse_line(line)
        if command is None:
            continue

        if command.kind is ExtendedCommandKind.CLICK:
            controller.click(command.x, command.y)
        elif command.kind is ExtendedCommandKind.JUMP:
            cell = board_mapper.pixel_to_cell(command.x, command.y)
            extra_engine.request_jump(cell)
        elif command.kind is ExtendedCommandKind.WAIT:
            extra_engine.wait(command.ms)
        elif command.kind is ExtendedCommandKind.PRINT_BOARD:
            print(printer.print(engine.board))


def main() -> None:
    lines = sys.stdin.read().splitlines()
    run_extra(lines)


if __name__ == "__main__":
    main()
