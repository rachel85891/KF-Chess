"""Surface: the abstract drawing-surface interface Renderer draws onto,
per spec.md §12. No concrete graphics/image library is wired in yet -
this project is CLI-only today, and spec.md §2 requires "the rendering
engine is thin and easily replaceable." RecordingSurface is the
minimal concrete implementation for now: it just records which calls
were made, in order, enough to unit-test Renderer without needing a
real image library. A future GUI step would supply a Surface backed by
an actual graphics library without Renderer itself changing.

Uses a TYPE_CHECKING-guarded import for PieceSnapshot to avoid a
runtime circular import with view.renderer (which imports Surface from
here) - safe because this module, like the rest of the codebase, uses
`from __future__ import annotations`, so annotations are never
evaluated at runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Protocol, Tuple

from kungfu_chess.model.position import Position

if TYPE_CHECKING:
    from kungfu_chess.view.renderer import PieceSnapshot


class Surface(Protocol):
    def draw_grid(self, width: int, height: int) -> None: ...

    def draw_piece(self, piece: PieceSnapshot) -> None: ...

    def draw_selection_highlight(self, cell: Position) -> None: ...

    def draw_game_over_message(self) -> None: ...


class RecordingSurface:
    def __init__(self):
        self.calls: List[Tuple[str, tuple]] = []

    def draw_grid(self, width: int, height: int) -> None:
        self.calls.append(("draw_grid", (width, height)))

    def draw_piece(self, piece: PieceSnapshot) -> None:
        self.calls.append(("draw_piece", (piece,)))

    def draw_selection_highlight(self, cell: Position) -> None:
        self.calls.append(("draw_selection_highlight", (cell,)))

    def draw_game_over_message(self) -> None:
        self.calls.append(("draw_game_over_message", ()))
