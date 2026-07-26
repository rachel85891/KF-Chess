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


def test_render_with_no_rating_change_draws_only_the_one_game_over_line():
    # Stage D3's own new, OPTIONAL parameter - omitting it must behave
    # byte-for-byte like before this stage (this class is shared by
    # every pre-existing caller that never knew about ratings at all).
    canvas = SpyImg()
    renderer = GameOverOverlayRenderer(canvas)

    renderer.render(winner_color=Color.WHITE)

    assert len(canvas.text_calls) == 1


def test_render_with_a_rating_gain_draws_a_second_line_with_old_arrow_new_and_a_signed_plus_delta():
    canvas = SpyImg()
    renderer = GameOverOverlayRenderer(canvas)

    renderer.render(winner_color=Color.WHITE, own_rating_change=(1200, 1216))

    assert len(canvas.text_calls) == 2
    rating_text = canvas.text_calls[1][0]
    assert "1200" in rating_text
    assert "1216" in rating_text
    assert "+16" in rating_text


def test_render_with_a_rating_loss_shows_a_signed_minus_delta():
    canvas = SpyImg()
    renderer = GameOverOverlayRenderer(canvas)

    renderer.render(winner_color=Color.BLACK, own_rating_change=(1280, 1260))

    rating_text = canvas.text_calls[1][0]
    assert "1280" in rating_text
    assert "1260" in rating_text
    assert "-20" in rating_text


def test_render_with_a_rating_change_draws_the_second_line_below_the_first():
    canvas = SpyImg()
    renderer = GameOverOverlayRenderer(canvas)

    renderer.render(winner_color=Color.WHITE, own_rating_change=(1200, 1216))

    first_y = canvas.text_calls[0][2]
    second_y = canvas.text_calls[1][2]
    assert second_y > first_y
