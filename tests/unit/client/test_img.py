from __future__ import annotations

from pathlib import Path

import pytest

from kungfu_chess.client.animation.state_config import PIECES_ROOT
from kungfu_chess.client.surface.img import ImageLoadError, Img, PasteOutOfBoundsError

QW_IDLE_FRAME_0 = PIECES_ROOT / "QW" / "states" / "idle" / "sprites" / "1.png"


def test_blank_canvas_has_the_requested_size():
    canvas = Img.blank_canvas(120, 80)

    assert canvas.width == 120
    assert canvas.height == 80


def test_load_raises_image_load_error_for_missing_file():
    missing_path = Path("definitely/does/not/exist.png")

    with pytest.raises(ImageLoadError) as exc_info:
        Img.load(missing_path)

    assert str(missing_path) in str(exc_info.value)


def test_load_a_real_sprite_returns_its_actual_pixel_size():
    sprite = Img.load(QW_IDLE_FRAME_0)

    assert sprite.width == 64
    assert sprite.height == 64


def test_paste_out_of_bounds_raises_paste_out_of_bounds_error():
    canvas = Img.blank_canvas(10, 10)
    sprite = Img.blank_canvas(20, 20)

    with pytest.raises(PasteOutOfBoundsError) as exc_info:
        canvas.paste(sprite, 0, 0)

    message = str(exc_info.value)
    assert "20x20" in message
    assert "10x10" in message


def test_paste_negative_position_raises_paste_out_of_bounds_error():
    canvas = Img.blank_canvas(10, 10)
    sprite = Img.blank_canvas(2, 2)

    with pytest.raises(PasteOutOfBoundsError):
        canvas.paste(sprite, -1, 0)


def test_paste_a_real_sprite_onto_a_canvas_does_not_raise():
    canvas = Img.blank_canvas(200, 200)
    sprite = Img.load(QW_IDLE_FRAME_0)

    canvas.paste(sprite, 10, 10)  # no exception == success; pixel-level rendering is not asserted here


def test_resize_returns_a_new_img_of_the_requested_size_and_leaves_the_original_unchanged():
    sprite = Img.load(QW_IDLE_FRAME_0)  # native 64x64

    shrunk = sprite.resize(32, 32)
    grown = sprite.resize(96, 96)

    assert shrunk.width == 32 and shrunk.height == 32
    assert grown.width == 96 and grown.height == 96
    assert sprite.width == 64 and sprite.height == 64  # original untouched


def test_resize_of_a_real_bgra_sprite_still_pastes_without_raising():
    # Img exposes no pixel-read-back API (by design - see img.py's own
    # SOLID boundary docstring), so this cannot assert alpha values
    # pixel-by-pixel; it does confirm resize()'s output is still a
    # valid 4-channel image paste() can alpha-blend, not something
    # paste()'s own alpha branch would choke on.
    sprite = Img.load(QW_IDLE_FRAME_0)  # native BGRA
    canvas = Img.blank_canvas(50, 50)

    resized = sprite.resize(20, 20)
    canvas.paste(resized, 5, 5)  # no exception == success

    assert resized.width == 20 and resized.height == 20
