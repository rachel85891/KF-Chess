"""ScriptRunner: composition root for text-driven runs, per spec.md
§13-15. Wires BoardParser -> GameEngine/Controller/RealTimeArbiter ->
BoardPrinter together for the first time - drives the public command
path (Controller.click, GameEngine.wait), never mutates the board or
duplicates game logic directly.

Reimplements a small, fresh Board:/Commands: section-splitter rather
than importing presentation/cli/cli_runner.py's private
_parse_sections - ~15 lines, trivial to reimplement, and keeps this
package decoupled from presentation/cli/. This preserves the existing,
already-verified external stdin contract exactly (Board:/Commands:
headers, "ERROR <code>" output), rather than spec.md §13's more
abbreviated literal DSL description - the same divergence between spec
prose and the real external contract found in earlier steps.

print board does not auto-settle due motions first (unlike the old
command_parser.py's _print_board): spec.md §14 already requires wait
to be called explicitly to observe an arrival ("...after enough time
has passed"), so every command sequence here calls wait before any
print board that needs to reflect an arrival.
"""

from __future__ import annotations

from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.input.controller import Controller
from kungfu_chess.io.board_parser import BoardParser
from kungfu_chess.io.board_printer import BoardPrinter
from kungfu_chess.texttests.script_parser import CommandKind, ScriptParser

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


class ScriptRunner:
    def run(self, lines: list[str]) -> None:
        board_lines, command_lines = _split_sections(lines)

        board, error = BoardParser().parse(board_lines)
        if error is not None:
            print(f"ERROR {error}")
            return

        engine = GameEngine(board)
        controller = Controller(engine)
        printer = BoardPrinter()
        parser = ScriptParser()

        for line in command_lines:
            command = parser.parse_line(line)
            if command is None:
                continue

            if command.kind is CommandKind.CLICK:
                controller.click(command.x, command.y)
            elif command.kind is CommandKind.WAIT:
                engine.wait(command.ms)
            elif command.kind is CommandKind.PRINT_BOARD:
                print(printer.print(engine.board))
