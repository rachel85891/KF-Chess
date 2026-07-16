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
