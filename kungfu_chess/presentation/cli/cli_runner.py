"""Composition root: reads a board fixture + commands from stdin,
validates the board, executes the commands, and writes canonical output
to stdout. No prompts, explanations, or debug text are ever printed -
only what the commands themselves produce (currently only 'print
board').

This is the only place that wires concrete implementations together
(TextBoardCodec, the standard chess PieceTypeRegistry, DEFAULT_GAME_RULES)
- a custom game would wire different ones here without touching
GameEngine or any service.
"""

import sys

from kungfu_chess.config.game_rules import DEFAULT_GAME_RULES
from kungfu_chess.config.piece_registry import PieceTypeRegistry
from kungfu_chess.infrastructure.codecs.text_board_codec import TextBoardCodec
from kungfu_chess.presentation.cli.command_parser import parse_command
from kungfu_chess.services.game_engine import GameEngine


def _parse_sections(lines: list[str]) -> tuple[list[str], list[str]]:
    """Split raw input lines into (board_lines, command_lines) based on
    the 'Board:' and 'Commands:' section headers."""
    board_lines: list[str] = []
    command_lines: list[str] = []
    section = None

    for line in lines:
        stripped = line.strip()
        if stripped == "Board:":
            section = "board"
            continue
        if stripped == "Commands:":
            section = "commands"
            continue
        if section == "board":
            if stripped == "":
                continue
            board_lines.append(stripped)
        elif section == "commands":
            if stripped == "":
                continue
            command_lines.append(stripped)

    return board_lines, command_lines


def main() -> None:
    data = sys.stdin.read()
    lines = data.splitlines()

    board_lines, command_lines = _parse_sections(lines)

    registry = PieceTypeRegistry.standard_chess()
    codec = TextBoardCodec()
    board, error = codec.decode(board_lines, registry)

    if error is not None:
        print(f"ERROR {error}")
        return

    engine = GameEngine(board, DEFAULT_GAME_RULES)

    for line in command_lines:
        command = parse_command(line, DEFAULT_GAME_RULES.cell_size)
        if command is not None:
            command(engine, codec)


if __name__ == "__main__":
    main()
