"""ScriptParser: parses one DSL command line into a Command, per
spec.md §13. Recognizes exactly three kinds - click/wait/print board -
matching spec.md §13's "exactly 4 commands" (Board is a section, not a
per-line command handled here). Any other line, including "jump ..."
(present in the old dispatcher but out of scope here - deferred to a
later, dedicated extra-features step), returns None and is silently
ignored, matching the old dispatcher's existing convention.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

_PRINT_BOARD_LINE = "print board"


class CommandKind(Enum):
    CLICK = auto()
    WAIT = auto()
    PRINT_BOARD = auto()


@dataclass(frozen=True)
class Command:
    kind: CommandKind
    x: Optional[int] = None
    y: Optional[int] = None
    ms: Optional[int] = None


class ScriptParser:
    def parse_line(self, line: str) -> Optional[Command]:
        parts = line.split()
        if not parts:
            return None

        if parts[0] == "click" and len(parts) == 3:
            return Command(kind=CommandKind.CLICK, x=int(parts[1]), y=int(parts[2]))

        if parts[0] == "wait" and len(parts) == 2:
            return Command(kind=CommandKind.WAIT, ms=int(parts[1]))

        if line == _PRINT_BOARD_LINE:
            return Command(kind=CommandKind.PRINT_BOARD)

        return None
