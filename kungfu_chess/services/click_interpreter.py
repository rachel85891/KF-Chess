"""Pure interpretation of "what does this click mean," given the current
selection and board/scheduler state. Bounds-checking, game-over guarding,
and actually acting on the intent (mutating selection, attempting a
move) live in GameEngine - this module only classifies the click.

SELECT covers both "nothing was selected yet" and "replace the current
selection with another friendly, idle piece": both cases resolve to the
same action (set selected = the clicked cell), so there is no separate
RESELECT kind - that would just be the same behavior under two names.
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from kungfu_chess.domain.board import Board
from kungfu_chess.services.move_scheduler import MoveScheduler

Cell = tuple[int, int]


class ClickIntentKind(Enum):
    IGNORE = auto()
    SELECT = auto()
    MOVE_REQUEST = auto()


@dataclass(frozen=True)
class ClickIntent:
    kind: ClickIntentKind
    cell: Optional[Cell] = None
    from_cell: Optional[Cell] = None
    to_cell: Optional[Cell] = None


def _is_selectable(board: Board, scheduler: MoveScheduler, row: int, col: int) -> bool:
    piece = board.get_piece(row, col)
    if piece is None:
        return False
    if scheduler.has_pending_move_from(row, col):
        return False
    if scheduler.is_airborne(row, col):
        return False
    return True


def interpret_click(
    selected: Optional[Cell], target: Cell, board: Board, scheduler: MoveScheduler
) -> ClickIntent:
    row, col = target

    if selected is None:
        if _is_selectable(board, scheduler, row, col):
            return ClickIntent(ClickIntentKind.SELECT, cell=target)
        return ClickIntent(ClickIntentKind.IGNORE)

    selected_piece = board.get_piece(*selected)
    target_piece = board.get_piece(row, col)

    if target_piece is not None and target_piece.color == selected_piece.color:
        if _is_selectable(board, scheduler, row, col):
            return ClickIntent(ClickIntentKind.SELECT, cell=target)
        return ClickIntent(ClickIntentKind.IGNORE)

    return ClickIntent(ClickIntentKind.MOVE_REQUEST, from_cell=selected, to_cell=target)
