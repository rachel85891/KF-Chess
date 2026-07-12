"""Entry point for the new model/rules/realtime/engine/io/input stack
(spec.md §4): reads a board fixture + commands from stdin, validates
the board, executes the commands, and writes canonical output to
stdout.

No prompts, explanations, or debug text are ever printed - only what
the commands themselves produce (currently only 'print board').

Coexists with main.py (the legacy domain/services engine's entry
point) - main.py is untouched here; cutting the "official" entry
point over to this one is a separate, later decision.
"""
from __future__ import annotations

import sys

from kungfu_chess.texttests.script_runner import ScriptRunner


def main() -> None:
    lines = sys.stdin.read().splitlines()
    ScriptRunner().run(lines)


if __name__ == "__main__":
    main()
