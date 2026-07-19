from __future__ import annotations

import pytest

from kungfu_chess.client.animation.piece_animator_registry import PieceAnimatorRegistry, UnknownPieceIdError
from kungfu_chess.client.animation.state_config import PIECES_ROOT
from kungfu_chess.client.events.game_events import MoveAccepted
from kungfu_chess.client.surface.asset_cache import AssetCache
from kungfu_chess.client.surface.img_surface import (
    PIECE_RENDER_OFFSET,
    PIECE_RENDER_SIZE,
    ImgSurface,
    UnknownPieceAssetError,
)
from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece, PieceKind, PieceState
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import CELL_SIZE
from kungfu_chess.view.renderer import PieceSnapshot


class SpyImg:
    """A fake canvas that only records which Img operations were
    called, with what arguments - no real cv2/window involved, per
    this stage's requirement to test ImgSurface without a real GUI."""

    def __init__(self, width: int = 800, height: int = 800):
        self.calls: list[tuple] = []
        self._width = width
        self._height = height

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    def paste(self, sprite, x, y):
        self.calls.append(("paste", sprite, x, y))

    def draw_rectangle(self, x, y, width, height, color, thickness=-1):
        self.calls.append(("draw_rectangle", x, y, width, height, color, thickness))

    def draw_text(self, text, x, y, color=(0, 0, 0), font_scale=1.0, thickness=1):
        self.calls.append(("draw_text", text, x, y, color, font_scale, thickness))


class _FakeKindOrColor:
    def __init__(self, value):
        self.value = value


class _FakeUnknownPiece:
    """Duck-typed stand-in for a PieceSnapshot whose kind+color combo
    matches no real assets/pieces/<KIND><COLOR> directory - PieceKind/
    Color are closed enums and all 12 real combos ARE vendored, so
    there is no way to build a genuinely-unknown combo through the
    real enums; this fake is the only way to exercise that path."""

    kind = _FakeKindOrColor("Z")
    color = _FakeKindOrColor("z")
    x = 0
    y = 0


def test_draw_grid_draws_checkerboard_rectangles_using_cell_size():
    canvas = SpyImg()
    surface = ImgSurface(canvas, AssetCache())

    surface.draw_grid(2, 2)

    assert len(canvas.calls) == 4
    assert all(call[0] == "draw_rectangle" for call in canvas.calls)
    assert canvas.calls[0][1:5] == (0, 0, CELL_SIZE, CELL_SIZE)
    assert canvas.calls[1][1:5] == (CELL_SIZE, 0, CELL_SIZE, CELL_SIZE)


def test_draw_piece_pastes_the_real_qw_idle_sprite_resized_and_centered_in_its_cell():
    asset_cache = AssetCache()
    canvas = SpyImg()
    surface = ImgSurface(canvas, asset_cache)
    piece = PieceSnapshot(id=1, kind=PieceKind.QUEEN, color=Color.WHITE, x=200, y=300, state=PieceState.IDLE)

    surface.draw_piece(piece)

    assert len(canvas.calls) == 1
    call_name, pasted_sprite, x, y = canvas.calls[0]
    assert call_name == "paste"
    # Centered: the snapshot position plus the fixed centering offset,
    # not the raw top-left corner (Stage 13a).
    assert x == 200 + PIECE_RENDER_OFFSET
    assert y == 300 + PIECE_RENDER_OFFSET

    # Resized: PIECE_RENDER_SIZE, not the sprite's native 64x64 - and
    # therefore a genuinely different Img than AssetCache's own cached,
    # native-resolution instance (identity, not just equal dimensions,
    # confirms this is ImgSurface's own resized copy, not a mutated
    # shared AssetCache entry - AssetCache's caching contract is
    # untouched).
    assert pasted_sprite.width == PIECE_RENDER_SIZE
    assert pasted_sprite.height == PIECE_RENDER_SIZE
    expected_sprite_path = PIECES_ROOT / "QW" / "states" / "idle" / "sprites" / "1.png"
    native_sprite = asset_cache.get(expected_sprite_path)
    assert pasted_sprite is not native_sprite
    assert native_sprite.width == 64 and native_sprite.height == 64


def test_draw_piece_reuses_the_cached_resized_sprite_on_a_second_call_for_the_same_path():
    asset_cache = AssetCache()
    canvas = SpyImg()
    surface = ImgSurface(canvas, asset_cache)
    piece = PieceSnapshot(id=1, kind=PieceKind.QUEEN, color=Color.WHITE, x=0, y=0, state=PieceState.IDLE)

    surface.draw_piece(piece)
    surface.draw_piece(piece)

    first_sprite = canvas.calls[0][1]
    second_sprite = canvas.calls[1][1]
    assert first_sprite is second_sprite


def test_draw_piece_raises_unknown_piece_asset_error_for_unmatched_kind_color():
    canvas = SpyImg()
    surface = ImgSurface(canvas, AssetCache())

    with pytest.raises(UnknownPieceAssetError) as exc_info:
        surface.draw_piece(_FakeUnknownPiece())

    message = str(exc_info.value)
    assert "Z" in message
    assert "z" in message


def test_draw_selection_highlight_draws_a_bordered_rectangle_at_the_cell_pixel_position():
    canvas = SpyImg()
    surface = ImgSurface(canvas, AssetCache())

    surface.draw_selection_highlight(Position(row=2, col=3))

    assert len(canvas.calls) == 1
    call = canvas.calls[0]
    assert call[0] == "draw_rectangle"
    assert call[1:5] == (3 * CELL_SIZE, 2 * CELL_SIZE, CELL_SIZE, CELL_SIZE)
    assert call[6] > 0  # a positive thickness, i.e. an outline, not a filled block (-1)


def test_draw_game_over_message_draws_text_on_the_canvas():
    canvas = SpyImg(width=800, height=800)
    surface = ImgSurface(canvas, AssetCache())

    surface.draw_game_over_message()

    assert len(canvas.calls) == 1
    call = canvas.calls[0]
    assert call[0] == "draw_text"
    assert call[1] == "GAME OVER"


def _board_with_one_white_queen() -> tuple[Board, Piece]:
    grid = [[None, None, None] for _ in range(3)]
    queen = Piece(color=Color.WHITE, kind=PieceKind.QUEEN, cell=Position(row=0, col=0))
    grid[0][0] = queen
    return Board(grid), queen


def test_draw_piece_with_registry_uses_the_live_animator_frame_not_static_idle():
    board, queen = _board_with_one_white_queen()
    registry = PieceAnimatorRegistry.from_board(board)
    registry.on_event(
        MoveAccepted(piece_id=queen.id, from_cell=Position(row=0, col=0), to_cell=Position(row=0, col=1), duration_ms=1000)
    )
    asset_cache = AssetCache()
    canvas = SpyImg()
    surface = ImgSurface(canvas, asset_cache, registry)
    piece_snapshot = PieceSnapshot(id=queen.id, kind=PieceKind.QUEEN, color=Color.WHITE, x=200, y=300, state=PieceState.MOVING)

    surface.draw_piece(piece_snapshot)

    assert len(canvas.calls) == 1
    call_name, pasted_sprite, x, y = canvas.calls[0]
    assert call_name == "paste"
    assert x == 200 + PIECE_RENDER_OFFSET
    assert y == 300 + PIECE_RENDER_OFFSET

    idle_sprite = asset_cache.get(PIECES_ROOT / "QW" / "states" / "idle" / "sprites" / "1.png")
    move_sprite = asset_cache.get(PIECES_ROOT / "QW" / "states" / "move" / "sprites" / "1.png")
    assert pasted_sprite is not move_sprite  # ImgSurface's own resized copy, not AssetCache's native instance
    assert pasted_sprite is not idle_sprite
    assert pasted_sprite.width == PIECE_RENDER_SIZE
    assert pasted_sprite.height == PIECE_RENDER_SIZE


def test_draw_piece_with_registry_raises_unknown_piece_id_error_for_id_the_registry_never_built():
    board, _queen = _board_with_one_white_queen()
    registry = PieceAnimatorRegistry.from_board(board)
    canvas = SpyImg()
    surface = ImgSurface(canvas, AssetCache(), registry)
    unknown_piece = PieceSnapshot(id=999999, kind=PieceKind.ROOK, color=Color.BLACK, x=0, y=0, state=PieceState.IDLE)

    with pytest.raises(UnknownPieceIdError) as exc_info:
        surface.draw_piece(unknown_piece)

    assert "999999" in str(exc_info.value)
