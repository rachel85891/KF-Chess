"""ExtendedScriptParser: the core ScriptParser's 3 commands plus
"jump <x> <y>", for the extras track only. Wraps
kungfu_chess.texttests.script_parser.ScriptParser rather than modifying
it - core/texttests/script_parser.py stays at exactly 3 recognized
commands, per spec.md §13.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from kungfu_chess.texttests.script_parser import Command, CommandKind, ScriptParser


class ExtendedCommandKind(Enum):
    CLICK = auto()
    WAIT = auto()
    PRINT_BOARD = auto()
    JUMP = auto()


@dataclass(frozen=True)
class ExtendedCommand:
    kind: ExtendedCommandKind
    x: Optional[int] = None
    y: Optional[int] = None
    ms: Optional[int] = None


_CORE_KIND_TO_EXTENDED = {
    CommandKind.CLICK: ExtendedCommandKind.CLICK,
    CommandKind.WAIT: ExtendedCommandKind.WAIT,
    CommandKind.PRINT_BOARD: ExtendedCommandKind.PRINT_BOARD,
}


def _from_core(command: Command) -> ExtendedCommand:
    return ExtendedCommand(kind=_CORE_KIND_TO_EXTENDED[command.kind], x=command.x, y=command.y, ms=command.ms)


class ExtendedScriptParser:
    def __init__(self):
        self._core_parser = ScriptParser()

    def parse_line(self, line: str) -> Optional[ExtendedCommand]:
        core_command = self._core_parser.parse_line(line)
        if core_command is not None:
            return _from_core(core_command)

        parts = line.split()
        if len(parts) == 3 and parts[0] == "jump":
            return ExtendedCommand(kind=ExtendedCommandKind.JUMP, x=int(parts[1]), y=int(parts[2]))

        return None
