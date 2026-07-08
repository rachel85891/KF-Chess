"""Entry point: reads a board fixture + commands from stdin, validates the
board, executes the commands, and writes canonical output to stdout.

No prompts, explanations, or debug text are ever printed - only what the
commands themselves produce (currently only 'print board').

The actual implementation lives in kungfu_chess/ (a layered package:
domain / services / infrastructure / presentation) - this file is just
the invocation entry point so `python main.py` keeps working unchanged.
"""

from kungfu_chess.presentation.cli.cli_runner import main

if __name__ == "__main__":
    main()
