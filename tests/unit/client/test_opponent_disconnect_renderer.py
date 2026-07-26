"""Unit tests for kungfu_chess/client/ui/opponent_disconnect_renderer.py
- a fake canvas recording draw_text calls only, mirroring
tests/unit/client/test_game_timer_renderer.py's own SpyImg convention
exactly, adapted to this renderer's one drawing method.
"""

from __future__ import annotations

from kungfu_chess.client.ui.opponent_disconnect_renderer import (
    OPPONENT_DISCONNECTED_TEXT_Y,
    OpponentDisconnectedRenderer,
)


class SpyImg:
    def __init__(self):
        self.text_calls: list[tuple] = []

    def draw_text(self, text, x, y, color=(0, 0, 0), font_scale=1.0, thickness=1):
        self.text_calls.append((text, x, y, color, font_scale, thickness))


def test_render_draws_a_message_naming_the_whole_remaining_seconds():
    canvas = SpyImg()
    renderer = OpponentDisconnectedRenderer(canvas)

    renderer.render(remaining_seconds=17.0, x=50)

    assert len(canvas.text_calls) == 1
    text, x, y, _color, _font_scale, _thickness = canvas.text_calls[0]
    assert "17" in text
    assert x == 50
    assert y == OPPONENT_DISCONNECTED_TEXT_Y


def test_render_rounds_up_a_fractional_remaining_second_rather_than_showing_zero_early():
    # A player watching a countdown expects it to keep reading a
    # positive number for as long as any real time is actually left -
    # showing "0s" a fraction of a second before the real resignation
    # would be a visibly wrong, premature signal.
    canvas = SpyImg()
    renderer = OpponentDisconnectedRenderer(canvas)

    renderer.render(remaining_seconds=0.4, x=0)

    text = canvas.text_calls[0][0]
    assert "resigning in 1s" in text


def test_render_clamps_a_negative_remaining_seconds_to_zero():
    canvas = SpyImg()
    renderer = OpponentDisconnectedRenderer(canvas)

    renderer.render(remaining_seconds=-3.0, x=0)

    text = canvas.text_calls[0][0]
    assert "resigning in 0s" in text


def test_render_mentions_disconnection_and_resignation_in_the_message():
    canvas = SpyImg()
    renderer = OpponentDisconnectedRenderer(canvas)

    renderer.render(remaining_seconds=20.0, x=0)

    text = canvas.text_calls[0][0].lower()
    assert "disconnect" in text
    assert "resign" in text
