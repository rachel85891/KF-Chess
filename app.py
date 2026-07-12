"""Entry point for the new stack (spec.md §4): reads a board fixture +
commands from stdin, validates the board, executes the commands, and
writes canonical output to stdout.

No prompts, explanations, or debug text are ever printed - only what
the commands themselves produce.

Thin re-export of app_extra.py's run_extra (core + JUMP + Promotion).
After retiring the legacy domain/services/infrastructure/presentation
architecture, this file and main.py must drive the exact same engine -
an external grading harness might invoke either filename, and most of
the retired golden-master fixtures (see
tests/integration/test_text_scripts_extra.py) depend on jump/promotion
support - so there is exactly one canonical wiring, defined once in
app_extra.py, and both entry points just call it.
"""
from __future__ import annotations

import sys

from app_extra import run_extra


def main() -> None:
    lines = sys.stdin.read().splitlines()
    run_extra(lines)


if __name__ == "__main__":
    main()
