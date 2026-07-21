"""Unit tests for kungfu_chess/client/ui/game_over_overlay_renderer.py -
a fake canvas recording draw_text calls only, mirroring
tests/unit/client/test_game_timer_renderer.py's own SpyImg convention
exactly, adapted to this renderer's one drawing method.
"""

from __future__ import annotations

from kungfu_chess.client.ui.game_over_overlay_renderer import GameOverOverlayRenderer
from kungfu_chess.model.color import Color


class SpyImg:
    def __init__(self, width=800, height=600):
        self.width = width
        self.height = height
        self.text_calls: list[tuple] = []

    def draw_text(self, text, x, y, color=(0, 0, 0), font_scale=1.0, thickness=1):
        self.text_calls.append((text, x, y, color, font_scale, thickness))


def test_render_draws_white_wins_message_for_a_white_winner():
    canvas = SpyImg()
    renderer = GameOverOverlayRenderer(canvas)

    renderer.render(winner_color=Color.WHITE)

    assert len(canvas.text_calls) == 1
    text, _x, _y, _color, _font_scale, _thickness = canvas.text_calls[0]
    assert "White" in text
    assert "wins" in text


def test_render_draws_black_wins_message_for_a_black_winner():
    canvas = SpyImg()
    renderer = GameOverOverlayRenderer(canvas)

    renderer.render(winner_color=Color.BLACK)

    text = canvas.text_calls[0][0]
    assert "Black" in text
    assert "wins" in text


def test_render_never_says_checkmate():
    # docs/spec.md §2 explicitly states this project does not implement
    # checkmate detection - only "a king can be captured; capturing the
    # opposing king ends the game" - so this message must not claim a
    # win condition that doesn't actually exist.
    canvas = SpyImg()
    renderer = GameOverOverlayRenderer(canvas)

    renderer.render(winner_color=Color.WHITE)

    text = canvas.text_calls[0][0]
    assert "Checkmate" not in text


def test_render_positions_the_message_relative_to_canvas_size():
    canvas = SpyImg(width=800, height=600)
    renderer = GameOverOverlayRenderer(canvas)

    renderer.render(winner_color=Color.WHITE)

    _text, x, y, _color, _font_scale, _thickness = canvas.text_calls[0]
    assert x == max(10, canvas.width // 4)
    assert y == canvas.height // 2
