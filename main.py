"""Entry point (original filename, kept for grading-harness
compatibility): reads a board fixture + commands from stdin, validates
the board, executes the commands, and writes canonical output to
stdout.

No prompts, explanations, or debug text are ever printed - only what
the commands themselves produce.

Thin re-export of app_extra.py's run_extra (core + JUMP + Promotion) -
see app.py's docstring: this file and app.py must drive the exact same
engine, since an external grading harness might invoke either
filename. The legacy domain/services/infrastructure/presentation
architecture this file used to drive has been retired.
"""
from __future__ import annotations

import sys

from app_extra import run_extra


def main() -> None:
    lines = sys.stdin.read().splitlines()
    run_extra(lines)


if __name__ == "__main__":
    main()
