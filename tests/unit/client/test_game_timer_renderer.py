"""Unit tests for kungfu_chess/client/ui/game_timer_renderer.py - a
fake canvas recording draw_text calls only, mirroring
tests/unit/client/test_cooldown_overlay_renderer.py's own SpyImg
convention exactly, adapted to the one drawing method this class
actually calls.
"""

from __future__ import annotations

from kungfu_chess.client.ui.game_timer_renderer import TIMER_TEXT_Y, GameTimerRenderer


class SpyImg:
    def __init__(self):
        self.text_calls: list[tuple] = []

    def draw_text(self, text, x, y, color=(0, 0, 0), font_scale=1.0, thickness=1):
        self.text_calls.append((text, x, y, color, font_scale, thickness))


def test_render_draws_zero_as_00_00():
    canvas = SpyImg()
    renderer = GameTimerRenderer(canvas)

    renderer.render(clock_ms=0, x=100)

    assert len(canvas.text_calls) == 1
    text, x, y, _color, _font_scale, _thickness = canvas.text_calls[0]
    assert "00:00" in text
    assert x == 100
    assert y == TIMER_TEXT_Y


def test_render_formats_minutes_and_seconds_correctly():
    canvas = SpyImg()
    renderer = GameTimerRenderer(canvas)

    renderer.render(clock_ms=(2 * 60 + 5) * 1000, x=0)

    text = canvas.text_calls[0][0]
    assert "02:05" in text


def test_render_truncates_partial_seconds_rather_than_rounding():
    canvas = SpyImg()
    renderer = GameTimerRenderer(canvas)

    renderer.render(clock_ms=59_999, x=0)

    text = canvas.text_calls[0][0]
    assert "00:59" in text


def test_render_clamps_a_negative_clock_ms_to_zero():
    canvas = SpyImg()
    renderer = GameTimerRenderer(canvas)

    renderer.render(clock_ms=-500, x=0)

    text = canvas.text_calls[0][0]
    assert "00:00" in text
