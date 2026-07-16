from __future__ import annotations

import pytest

from kungfu_chess.client.animation.state_config import PIECES_ROOT
from kungfu_chess.client.surface.asset_cache import AssetCache
from kungfu_chess.client.surface.img import ImageLoadError, Img

QW_IDLE_FRAME_0 = PIECES_ROOT / "QW" / "states" / "idle" / "sprites" / "1.png"


def test_get_loads_a_real_vendored_sprite():
    cache = AssetCache()

    sprite = cache.get(QW_IDLE_FRAME_0)

    assert isinstance(sprite, Img)
    assert sprite.width > 0
    assert sprite.height > 0


def test_get_caches_and_does_not_reload_from_disk_on_second_call(monkeypatch):
    cache = AssetCache()
    original_load = Img.load
    load_calls = []

    def counting_load(path):
        load_calls.append(path)
        return original_load(path)

    monkeypatch.setattr(Img, "load", counting_load)

    first = cache.get(QW_IDLE_FRAME_0)
    second = cache.get(QW_IDLE_FRAME_0)

    assert len(load_calls) == 1
    assert first is second


def test_get_raises_image_load_error_for_nonexistent_path():
    cache = AssetCache()
    missing_path = PIECES_ROOT / "QW" / "states" / "idle" / "sprites" / "does_not_exist.png"

    with pytest.raises(ImageLoadError) as exc_info:
        cache.get(missing_path)

    assert str(missing_path) in str(exc_info.value)
