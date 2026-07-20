"""server/algebraic_notation.py: THIN RE-EXPORT SHIM (Stage B5).

The real implementation used to live here (Stage B3), one-directional
(square->Position only). Stage B5 relocated it to
kungfu_chess/notation/algebraic_notation.py - see that module's own
docstring for the full reasoning - because a CLIENT needs the exact
same conversion logic (in BOTH directions now) to build outgoing move
commands, and a client must never import from server/ (server depends
on kungfu_chess/, never the reverse - docs/spec.md §4's dependency
list).

This file is kept, with its original public surface intact, purely so
tests/unit/server/test_algebraic_notation.py (and anything else still
importing this exact path) keeps working with ZERO test-file edits -
the same "one implementation, multiple import paths" pattern this
project already established for main.py/app.py's own thin re-export of
app_extra.run_extra (see docs/README.md). server/move_command.py
itself was updated to import directly from the new
kungfu_chess.notation.algebraic_notation location, not through this
shim - this file exists only for backward-compatible external imports,
not because anything under server/ still needs it.
"""

from __future__ import annotations

from kungfu_chess.notation.algebraic_notation import (
    BOARD_SIZE,
    InvalidPositionError,
    InvalidSquareError,
    algebraic_to_position,
    position_to_algebraic,
)

__all__ = [
    "BOARD_SIZE",
    "InvalidPositionError",
    "InvalidSquareError",
    "algebraic_to_position",
    "position_to_algebraic",
]
