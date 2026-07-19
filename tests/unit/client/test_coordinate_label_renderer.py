from __future__ import annotations

from kungfu_chess.client.ui.coordinate_label_renderer import (
    LABEL_COLOR,
    LABEL_FONT_SCALE,
    LABEL_MARGIN,
    LABEL_THICKNESS,
    APPROX_HALF_CHAR_HEIGHT,
    APPROX_HALF_CHAR_WIDTH,
    CoordinateLabelRenderer,
)
from kungfu_chess.realtime.real_time_arbiter import CELL_SIZE


class SpyImg:
    """A fake canvas recording draw_text calls only - the same
    black-box-canvas approach as this suite's other renderer tests
    (test_cooldown_overlay_renderer.py/test_hud_renderer.py): no real
    cv2/window involved."""

    def __init__(self):
        self.text_calls: list[tuple] = []

    def draw_text(self, text, x, y, color=(0, 0, 0), font_scale=1.0, thickness=1):
        self.text_calls.append((text, x, y, color, font_scale, thickness))


def test_render_draws_each_file_letter_twice_and_each_rank_number_twice():
    # Stage 15: labels now appear on BOTH sides (above+below for
    # files, left+right for ranks), not just one side each.
    canvas = SpyImg()
    CoordinateLabelRenderer(canvas).render(board_width=8, board_height=8, board_origin_x=0, board_origin_y=0)

    letters = [call[0] for call in canvas.text_calls if call[0].isalpha()]
    numbers = [call[0] for call in canvas.text_calls if call[0].isdigit()]
    assert sorted(letters) == sorted(["a", "b", "c", "d", "e", "f", "g", "h"] * 2)
    assert sorted(numbers) == sorted(["8", "7", "6", "5", "4", "3", "2", "1"] * 2)


def test_file_labels_are_positioned_below_the_board_centered_per_column_using_the_origin():
    canvas = SpyImg()
    CoordinateLabelRenderer(canvas).render(board_width=3, board_height=3, board_origin_x=40, board_origin_y=50)

    below_y = 50 + 3 * CELL_SIZE + LABEL_MARGIN // 2 + APPROX_HALF_CHAR_HEIGHT
    below_calls = [call for call in canvas.text_calls if call[0].isalpha() and call[2] == below_y]
    assert len(below_calls) == 3

    for col, call in enumerate(below_calls):
        text, x, y, color, font_scale, thickness = call
        assert text == chr(ord("a") + col)
        assert x == 40 + col * CELL_SIZE + CELL_SIZE // 2 - APPROX_HALF_CHAR_WIDTH
        assert color == LABEL_COLOR
        assert font_scale == LABEL_FONT_SCALE
        assert thickness == LABEL_THICKNESS


def test_file_labels_are_positioned_above_the_board_centered_per_column_using_the_origin():
    canvas = SpyImg()
    CoordinateLabelRenderer(canvas).render(board_width=3, board_height=3, board_origin_x=40, board_origin_y=50)

    above_y = 50 - LABEL_MARGIN + LABEL_MARGIN // 2 + APPROX_HALF_CHAR_HEIGHT
    above_calls = [call for call in canvas.text_calls if call[0].isalpha() and call[2] == above_y]
    assert len(above_calls) == 3

    for col, call in enumerate(above_calls):
        text, x, y, color, font_scale, thickness = call
        assert text == chr(ord("a") + col)
        assert x == 40 + col * CELL_SIZE + CELL_SIZE // 2 - APPROX_HALF_CHAR_WIDTH
        assert color == LABEL_COLOR
        assert font_scale == LABEL_FONT_SCALE
        assert thickness == LABEL_THICKNESS


def test_rank_labels_are_positioned_left_of_the_board_centered_per_row_using_the_origin():
    canvas = SpyImg()
    CoordinateLabelRenderer(canvas).render(board_width=3, board_height=3, board_origin_x=40, board_origin_y=50)

    left_x = 40 - LABEL_MARGIN + APPROX_HALF_CHAR_WIDTH
    left_calls = [call for call in canvas.text_calls if call[0].isdigit() and call[1] == left_x]
    assert len(left_calls) == 3

    for row, call in enumerate(left_calls):
        text, x, y, color, font_scale, thickness = call
        assert text == str(3 - row)
        assert y == 50 + row * CELL_SIZE + CELL_SIZE // 2 + APPROX_HALF_CHAR_HEIGHT
        assert color == LABEL_COLOR
        assert font_scale == LABEL_FONT_SCALE
        assert thickness == LABEL_THICKNESS


def test_rank_labels_are_positioned_right_of_the_board_centered_per_row_using_the_origin():
    canvas = SpyImg()
    CoordinateLabelRenderer(canvas).render(board_width=3, board_height=3, board_origin_x=40, board_origin_y=50)

    right_x = 40 + 3 * CELL_SIZE + APPROX_HALF_CHAR_WIDTH
    right_calls = [call for call in canvas.text_calls if call[0].isdigit() and call[1] == right_x]
    assert len(right_calls) == 3

    for row, call in enumerate(right_calls):
        text, x, y, color, font_scale, thickness = call
        assert text == str(3 - row)
        assert y == 50 + row * CELL_SIZE + CELL_SIZE // 2 + APPROX_HALF_CHAR_HEIGHT
        assert color == LABEL_COLOR
        assert font_scale == LABEL_FONT_SCALE
        assert thickness == LABEL_THICKNESS


def test_render_draws_exactly_twice_width_plus_height_labels_total():
    canvas = SpyImg()
    CoordinateLabelRenderer(canvas).render(board_width=5, board_height=8, board_origin_x=0, board_origin_y=0)

    assert len(canvas.text_calls) == 2 * (5 + 8)
