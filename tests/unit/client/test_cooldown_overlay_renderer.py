from __future__ import annotations

from kungfu_chess.client.events.cooldown_tracker import CooldownTracker
from kungfu_chess.client.events.game_events import PieceArrived
from kungfu_chess.client.ui.cooldown_overlay_renderer import COOLDOWN_BAR_HEIGHT, CooldownOverlayRenderer
from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece, PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import CELL_SIZE


class SpyImg:
    """A fake canvas recording draw_rectangle calls only - the same
    approach as Stage 9/6's test_hud_renderer.py/test_img_surface.py:
    no real cv2/window involved."""

    def __init__(self):
        self.rectangle_calls: list[tuple] = []

    def draw_rectangle(self, x, y, width, height, color, thickness=-1):
        self.rectangle_calls.append((x, y, width, height, color, thickness))


def _empty_grid(rows: int, cols: int) -> list[list[None]]:
    return [[None for _ in range(cols)] for _ in range(rows)]


def _piece(color: Color, kind: PieceKind, cell: Position) -> Piece:
    return Piece(color=color, kind=kind, cell=cell)


def test_piece_at_full_ratio_draws_a_full_width_bar():
    grid = _empty_grid(2, 2)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)

    tracker = CooldownTracker()
    tracker.set_current_clock_ms(1000)
    tracker.on_event(PieceArrived(piece_id=rook.id, cell=Position(row=0, col=0), captured_piece_id=None))

    canvas = SpyImg()
    CooldownOverlayRenderer(canvas).render(board, tracker, current_clock_ms=1000)

    assert len(canvas.rectangle_calls) == 1
    x, y, width, height, _color, _thickness = canvas.rectangle_calls[0]
    assert x == 0
    assert y == CELL_SIZE - COOLDOWN_BAR_HEIGHT
    assert width == CELL_SIZE
    assert height == COOLDOWN_BAR_HEIGHT


def test_piece_at_half_ratio_draws_a_half_width_bar():
    grid = _empty_grid(2, 2)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=1, col=1))
    grid[1][1] = rook
    board = Board(grid)

    tracker = CooldownTracker()
    tracker.set_current_clock_ms(0)
    tracker.on_event(PieceArrived(piece_id=rook.id, cell=Position(row=1, col=1), captured_piece_id=None))

    canvas = SpyImg()
    CooldownOverlayRenderer(canvas).render(board, tracker, current_clock_ms=500)  # COOLDOWN_MS is 1000 -> ratio 0.5

    assert len(canvas.rectangle_calls) == 1
    x, y, width, height, _color, _thickness = canvas.rectangle_calls[0]
    assert x == CELL_SIZE
    assert y == CELL_SIZE + CELL_SIZE - COOLDOWN_BAR_HEIGHT
    assert width == CELL_SIZE // 2
    assert height == COOLDOWN_BAR_HEIGHT


def test_piece_with_zero_ratio_draws_nothing():
    grid = _empty_grid(2, 2)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)

    tracker = CooldownTracker()  # never told about any PieceArrived

    canvas = SpyImg()
    CooldownOverlayRenderer(canvas).render(board, tracker, current_clock_ms=1000)

    assert canvas.rectangle_calls == []


def test_empty_board_draws_nothing():
    board = Board(_empty_grid(3, 3))
    tracker = CooldownTracker()

    canvas = SpyImg()
    CooldownOverlayRenderer(canvas).render(board, tracker, current_clock_ms=0)

    assert canvas.rectangle_calls == []
