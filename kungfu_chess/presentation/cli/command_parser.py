"""Parses one text protocol line ('click x y' / 'jump x y' / 'wait ms' /
'print board') into a callable that acts on a GameEngine + BoardCodec.
Unknown commands and malformed argument counts return None and are
silently ignored by the caller - matching the original dispatcher.

This is also where pixel-to-cell translation happens: GameEngine only
ever sees (row, col), never pixels - a future GUI would do its own
pixel math and call engine.handle_click(row, col) directly, bypassing
this text parsing entirely.

A plain function returning a Callable, not a Command class hierarchy:
there is no queuing, undo, or replay need here that would justify the
extra ceremony of Command objects for four one-line actions.
"""

from typing import Callable, Optional

from kungfu_chess.infrastructure.codecs.board_codec import BoardCodec
from kungfu_chess.services.game_engine import GameEngine

EngineCommand = Callable[[GameEngine, BoardCodec], None]

_PRINT_BOARD_LINE = "print board"


def _pixel_to_cell(x: int, y: int, cell_size: int) -> tuple[int, int]:
    col = x // cell_size
    row = y // cell_size
    return row, col


def _print_board(engine: GameEngine, codec: BoardCodec) -> None:
    # Settle first so the printed board always reflects the current
    # clock time, even if called without an intervening wait.
    engine.settle_due_events()
    print(codec.encode(engine.board))


def parse_command(line: str, cell_size: int) -> Optional[EngineCommand]:
    parts = line.split()
    if not parts:
        return None

    if parts[0] == "click" and len(parts) == 3:
        row, col = _pixel_to_cell(int(parts[1]), int(parts[2]), cell_size)
        return lambda engine, codec: engine.handle_click(row, col)

    if parts[0] == "jump" and len(parts) == 3:
        row, col = _pixel_to_cell(int(parts[1]), int(parts[2]), cell_size)
        return lambda engine, codec: engine.handle_jump(row, col)

    if parts[0] == "wait" and len(parts) == 2:
        ms = int(parts[1])
        return lambda engine, codec: engine.handle_wait(ms)

    if line == _PRINT_BOARD_LINE:
        return _print_board

    return None
