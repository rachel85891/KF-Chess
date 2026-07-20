"""move_command_format.py: formats a move command in the exact wire
grammar server/move_command.py's parse_move_command already accepts -
"<W|B><K|Q|R|B|N|P><file><rank><file><rank>", e.g. "WQe2e5" - the
exact reverse of that parser.

WHY THIS LIVES HERE, NOT IN server/move_command.py: a client needs to
BUILD outgoing commands from a color/piece kind/two Positions (e.g.
after a player clicks a piece and a destination), but a client must
never import from server/ (see algebraic_notation.py's own docstring
in this same package for the full "server depends on kungfu_chess/,
never the reverse" reasoning - it applies identically here). Putting
the formatter in the shared kungfu_chess/notation/ package, alongside
algebraic_notation.py, means both the server's own parser
(server/move_command.py) and a future client can each depend on
kungfu_chess/notation/ - never on each other - for this shared,
symmetric piece of protocol knowledge.

REUSES algebraic_notation.position_to_algebraic for the square-
formatting half, rather than re-deriving file/rank text itself - the
one square<->string conversion this project has stays in exactly one
place (kungfu_chess/notation/algebraic_notation.py), per this stage's
own DRY requirement.

Color/piece letters are taken directly from the existing enums'
already-established representations - `PieceKind.value` is already the
correct board-notation letter (e.g. PieceKind.ROOK.value == "R" -
kungfu_chess/io/board_parser.py already relies on this same fact), and
`Color.name[0]` gives "W"/"B" from Color.WHITE/Color.BLACK - no new
letter-mapping table is introduced; this reuses the exact same facts
server/move_command.py's own parser already reverses
(Color(letter.lower()), PieceKind(letter.upper())).
"""

from __future__ import annotations

from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.notation.algebraic_notation import position_to_algebraic


def format_move_command(color: Color, piece_kind: PieceKind, from_cell: Position, to_cell: Position) -> str:
    """Format a move command in the "WQe2e5"-style grammar
    server/move_command.py's parse_move_command already accepts.

    Args:
        color: The mover's color.
        piece_kind: The moving piece's kind - informational, per the
            wire format (server/move_command.py's own docstring: the
            actual move is driven by the two Positions, not this
            letter).
        from_cell: The Position the piece currently occupies.
        to_cell: The Position it is being moved to.

    Returns:
        The exact 6-character command string, e.g. "WQe2e5".

    Raises:
        InvalidPositionError: If either Position is outside the 8x8
            board (propagated from position_to_algebraic).
    """

    color_letter = color.name[0]
    piece_letter = piece_kind.value
    return f"{color_letter}{piece_letter}{position_to_algebraic(from_cell)}{position_to_algebraic(to_cell)}"
