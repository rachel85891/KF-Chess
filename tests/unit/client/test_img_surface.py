from __future__ import annotations

import pytest

from kungfu_chess.client.animation.state_config import PIECES_ROOT
from kungfu_chess.client.surface.asset_cache import AssetCache
from kungfu_chess.client.surface.img_surface import ImgSurface, UnknownPieceAssetError
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind, PieceState
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


def test_draw_piece_pastes_the_real_qw_idle_sprite_at_the_snapshot_position():
    asset_cache = AssetCache()
    canvas = SpyImg()
    surface = ImgSurface(canvas, asset_cache)
    piece = PieceSnapshot(id=1, kind=PieceKind.QUEEN, color=Color.WHITE, x=200, y=300, state=PieceState.IDLE)

    surface.draw_piece(piece)

    assert len(canvas.calls) == 1
    call_name, pasted_sprite, x, y = canvas.calls[0]
    assert call_name == "paste"
    assert x == 200
    assert y == 300

    expected_sprite_path = PIECES_ROOT / "QW" / "states" / "idle" / "sprites" / "1.png"
    assert pasted_sprite is asset_cache.get(expected_sprite_path)


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
