"""Unit tests for kungfu_chess/client/input/window_fit.py's
compute_fit_scale_and_origin - pure, no cv2/real window involved at
all (per this module's own docstring: this is the one piece of the
resizable-window fix that CAN be thoroughly unit-tested without a real
display, so the aspect-ratio-preserving fit/letterbox math is
extracted here specifically to make that possible).
"""

from __future__ import annotations

from kungfu_chess.client.input.window_fit import compute_fit_scale_and_origin


def test_exact_match_needs_no_scaling_or_letterboxing():
    scale, origin_x, origin_y = compute_fit_scale_and_origin(400, 300, 400, 300)

    assert scale == 1.0
    assert origin_x == 0.0
    assert origin_y == 0.0


def test_uniformly_larger_window_matching_aspect_ratio_scales_up_with_no_letterbox():
    # 400x300 is 4:3 - 800x600 is also 4:3 (2x).
    scale, origin_x, origin_y = compute_fit_scale_and_origin(400, 300, 800, 600)

    assert scale == 2.0
    assert origin_x == 0.0
    assert origin_y == 0.0


def test_wider_than_canvas_window_letterboxes_horizontally():
    # Window is much wider than the canvas's own aspect ratio allows -
    # height is the binding constraint (scale = window_h / canvas_h),
    # leaving empty margin on the left and right (pillarboxing).
    scale, origin_x, origin_y = compute_fit_scale_and_origin(400, 300, 1000, 300)

    assert scale == 1.0
    assert origin_x == 300.0  # (1000 - 400*1.0) / 2
    assert origin_y == 0.0


def test_taller_than_canvas_window_letterboxes_vertically():
    # Width is the binding constraint here - empty margin above and
    # below (letterboxing proper).
    scale, origin_x, origin_y = compute_fit_scale_and_origin(400, 300, 400, 900)

    assert scale == 1.0
    assert origin_x == 0.0
    assert origin_y == 300.0  # (900 - 300*1.0) / 2


def test_non_proportional_shrink_still_uses_one_uniform_scale_and_centers_both_axes():
    # Neither axis matches the canvas's own 4:3 ratio - scale must
    # still be a single uniform factor (the smaller of the two ratios),
    # with the un-filled remainder centered on the OTHER axis too, not
    # independently stretched to fill the window on both axes.
    scale, origin_x, origin_y = compute_fit_scale_and_origin(400, 300, 200, 200)

    assert scale == 0.5  # min(200/400, 200/300) = min(0.5, 0.667) = 0.5
    assert origin_x == 0.0  # 200 - 400*0.5 = 0, already exact fit on this axis
    assert origin_y == 25.0  # (200 - 300*0.5) / 2 = (200 - 150) / 2


def test_degenerate_zero_width_window_returns_zero_scale_without_raising():
    scale, origin_x, origin_y = compute_fit_scale_and_origin(400, 300, 0, 600)

    assert scale == 0.0


def test_degenerate_zero_height_window_returns_zero_scale_without_raising():
    scale, origin_x, origin_y = compute_fit_scale_and_origin(400, 300, 800, 0)

    assert scale == 0.0


def test_degenerate_zero_size_window_returns_zero_scale_without_raising():
    scale, origin_x, origin_y = compute_fit_scale_and_origin(400, 300, 0, 0)

    assert scale == 0.0


def test_negative_window_dimensions_also_do_not_raise_and_yield_non_positive_scale():
    # cv2.getWindowImageRect is not documented to return negative sizes
    # in practice, but a defensive caller (the two Runner classes) only
    # needs "scale > 0 means trust this result" to hold - a pure
    # negative-in-negative-out here, with no exception, is sufficient
    # for that check to work correctly without this function itself
    # needing to special-case negative input.
    scale, origin_x, origin_y = compute_fit_scale_and_origin(400, 300, -10, -10)

    assert scale <= 0.0
