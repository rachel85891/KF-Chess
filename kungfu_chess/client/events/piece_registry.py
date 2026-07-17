"""PieceRegistry: piece_id -> (kind, color) lookup, per client_spec.md
§6. Exists because PieceArrived (game_events.py) carries only
piece_id/cell/captured_piece_id - no kind/color - so any Observer that
needs to know WHAT was captured (ScoreObserver, MovesLogObserver) needs
somewhere else to look that up.

WHY a one-time snapshot at game start, not live Board access: Piece.id
is assigned once at construction and never reused for that piece's
whole lifecycle (kungfu_chess/model/piece.py's own documented
invariant) - so a snapshot taken once, at construction, stays valid and
complete for the entire game, including pieces later captured/removed
from the live board (a live Board lookup would fail for exactly the
piece a capture event is asking about, since Board.remove_piece has
already run by the time PieceArrived is published). This is also what
lets every Observer avoid holding a live Board/GameEngine reference at
all (DIP) - they only need this small, static lookup, built once by
whoever wires the Observers up.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position


class PieceRegistryError(Exception):
    """Base class for PieceRegistry errors, matching the same
    one-class-per-failure-mode convention used throughout this
    codebase (BoardError, StateConfigError, etc.)."""


class UnknownPieceIdError(PieceRegistryError):
    """info_for() was asked about a piece_id absent from the board
    snapshot this registry was built from - see info_for's own
    docstring for what this means in practice."""


@dataclass(frozen=True)
class PieceInfo:
    """The two facts every Observer actually needs about a piece that
    PieceArrived's bare piece_id doesn't itself carry."""

    kind: PieceKind
    color: Color


class PieceRegistry:
    def __init__(self, info_by_id: Dict[int, PieceInfo]) -> None:
        """Wrap an already-built id -> PieceInfo mapping. Most callers
        should use from_board() instead - this constructor is exposed
        mainly for tests that want precise, hand-built control over
        exactly which ids exist."""

        self._info_by_id = info_by_id

    @classmethod
    def from_board(cls, board: Board) -> "PieceRegistry":
        """Snapshot every piece currently on `board` into a new
        registry (see module docstring for why a one-time snapshot is
        valid for the whole game).

        Iterates every (row, col) via board.piece_at rather than
        reaching into Board's private cell storage - the same
        enumeration idiom kungfu_chess/view/renderer.py's
        build_snapshot already uses, so this doesn't invent a second
        way to walk a Board.
        """

        info_by_id: Dict[int, PieceInfo] = {}
        for row in range(board.height):
            for col in range(board.width):
                piece = board.piece_at(Position(row=row, col=col))
                if piece is not None:
                    info_by_id[piece.id] = PieceInfo(kind=piece.kind, color=piece.color)
        return cls(info_by_id)

    def info_for(self, piece_id: int) -> PieceInfo:
        """Look up a piece's kind/color by id.

        Raises:
            UnknownPieceIdError: If piece_id was never on the board
                this registry was snapshotted from. This should only
                ever happen from a real data-integrity bug upstream
                (an event referencing a piece that never existed) -
                not a normal runtime condition - so it is raised as a
                specific, named exception rather than a bare KeyError,
                letting it surface loudly rather than being masked.
        """

        try:
            return self._info_by_id[piece_id]
        except KeyError as exc:
            raise UnknownPieceIdError(f"piece_id={piece_id} was never present on this registry's board snapshot") from exc
