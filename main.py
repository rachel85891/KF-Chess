"""
Entry point: reads a board fixture + commands from stdin, validates the
board, executes the commands, and writes canonical output to stdout.

No prompts, explanations, or debug text are ever printed - only what the
commands themselves produce (currently only 'print board').
"""

import sys

from board import parse_sections, Board
from game import GameState
from commands import run_commands


def main():
    data = sys.stdin.read()
    lines = data.splitlines()

    board_lines, command_lines = parse_sections(lines)
    board, error = Board.from_lines(board_lines)

    if error is not None:
        print(f"ERROR {error}")
        return

    state = GameState(board)
    run_commands(state, command_lines)


if __name__ == "__main__":
    main()


