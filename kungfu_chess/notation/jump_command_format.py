"""jump_command_format.py: formats a jump command in the exact wire
grammar kungfu_chess/notation/jump_command.py's parse_jump_command
already accepts - "J<W|B><K|Q|R|B|N|P><file><rank>", e.g. "JWRe2" - the
exact reverse of that parser. Mirrors move_command_format.py's own
reasoning and shape closely (one square instead of two, and the
leading JUMP_COMMAND_PREFIX marker jump_command.py's own docstring
documents).

Lives alongside jump_command.py in kungfu_chess/notation/ (not
server/) for the identical reason move_command_format.py already lives
here rather than in server/: a client must never import from server/
(see algebraic_notation.py's own docstring), so the shared formatting
logic lives in the one package both a server-side parser and a
client-side formatter can each depend on without depending on each
other.

REUSES algebraic_notation.position_to_algebraic for the square-
formatting half and JUMP_COMMAND_PREFIX/color-letter/piece-letter
conventions already established by jump_command.py/
move_command_format.py - no new letter-mapping table or square
serialization is introduced here.
"""

from __future__ import annotations

from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.notation.algebraic_notation import position_to_algebraic
from kungfu_chess.notation.jump_command import JUMP_COMMAND_PREFIX


def format_jump_command(color: Color, piece_kind: PieceKind, cell: Position) -> str:
    """Format a jump command in the "JWRe2"-style grammar
    kungfu_chess/notation/jump_command.py's parse_jump_command already
    accepts.

    Args:
        color: The jumping piece's color.
        piece_kind: The jumping piece's kind - informational, per the
            wire format (mirrors move_command_format.py's own
            piece_kind parameter: the actual jump is driven by `cell`
            alone, not this letter).
        cell: The Position the jumping piece currently occupies (its
            own cell - not a from/to pair, matching
            ExtraEngine.request_jump's own single-cell contract).

    Returns:
        The exact 5-character command string, e.g. "JWRe2".

    Raises:
        InvalidPositionError: If `cell` is outside the 8x8 board
            (propagated from position_to_algebraic).
    """

    color_letter = color.name[0]
    piece_letter = piece_kind.value
    return f"{JUMP_COMMAND_PREFIX}{color_letter}{piece_letter}{position_to_algebraic(cell)}"
