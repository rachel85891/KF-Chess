"""score_table: PIECE_VALUES, per client_spec.md §6's component table
("ScoreObserver | ... | Observer, score_table"). Pure data, no logic
(SRP) - ScoreObserver is the only consumer.

Standard chess piece values. KING maps to 0: a king capture ends the
game via GameOver (the win condition), it is never itself "scored" the
way an ordinary capture adds material value - mapping it to 0 rather
than omitting it keeps PIECE_VALUES total over every PieceKind, so
ScoreObserver can look PIECE_VALUES[kind] up unconditionally for any
captured piece without a special case for KING in its own logic.
"""

from __future__ import annotations

from typing import Dict

from kungfu_chess.model.piece import PieceKind

PIECE_VALUES: Dict[PieceKind, int] = {
    PieceKind.PAWN: 1,
    PieceKind.KNIGHT: 3,
    PieceKind.BISHOP: 3,
    PieceKind.ROOK: 5,
    PieceKind.QUEEN: 9,
    PieceKind.KING: 0,
}
