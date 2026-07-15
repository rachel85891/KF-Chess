import pytest

from kungfu_chess.client.input.screen_mapper import ImagePosition, InvalidWindowScaleError, ScreenToImageMapper


def test_identity_when_origin_zero_and_scale_one():
    mapper = ScreenToImageMapper(window_origin=(0, 0), window_scale=1.0)

    result = mapper.to_image(50, 75)

    assert result == ImagePosition(x=50.0, y=75.0)


def test_non_zero_origin_and_non_one_scale():
    mapper = ScreenToImageMapper(window_origin=(20, 10), window_scale=2.0)

    result = mapper.to_image(120, 210)

    assert result == ImagePosition(x=50.0, y=100.0)


def test_click_exactly_on_a_cell_boundary():
    # CELL_SIZE is 100 elsewhere in the codebase; a click at the exact
    # boundary between cell 2 and cell 3 should map to image pixel 300.0
    # with no rounding surprises, since to_image is pure float division.
    mapper = ScreenToImageMapper(window_origin=(0, 0), window_scale=1.0)

    result = mapper.to_image(300, 400)

    assert result == ImagePosition(x=300.0, y=400.0)


def test_out_of_bounds_screen_coordinates_pass_through_unclamped():
    # Documented choice: to_image never raises or clamps - it always
    # returns the raw transformed coordinate. Bounds checking against
    # an actual board is a different layer's responsibility.
    mapper = ScreenToImageMapper(window_origin=(50, 50), window_scale=1.0)

    negative = mapper.to_image(0, 0)
    beyond_max = mapper.to_image(10_000, 10_000)

    assert negative == ImagePosition(x=-50.0, y=-50.0)
    assert beyond_max == ImagePosition(x=9_950.0, y=9_950.0)


def test_different_instances_can_use_different_origin_and_scale():
    # ScreenToImageMapper is an immutable frozen dataclass (matching
    # Position's own convention in this codebase): a window resize is
    # represented by constructing a new mapper, not mutating one.
    mapper_a = ScreenToImageMapper(window_origin=(0, 0), window_scale=1.0)
    mapper_b = ScreenToImageMapper(window_origin=(10, 20), window_scale=0.5)

    result_a = mapper_a.to_image(10, 10)
    result_b = mapper_b.to_image(10, 10)

    assert result_a == ImagePosition(x=10.0, y=10.0)
    assert result_b == ImagePosition(x=0.0, y=-20.0)


def test_zero_window_scale_raises_invalid_window_scale_error():
    with pytest.raises(InvalidWindowScaleError) as exc_info:
        ScreenToImageMapper(window_origin=(0, 0), window_scale=0)

    assert "0" in str(exc_info.value)


def test_negative_window_scale_raises_invalid_window_scale_error():
    with pytest.raises(InvalidWindowScaleError) as exc_info:
        ScreenToImageMapper(window_origin=(0, 0), window_scale=-2.5)

    assert "-2.5" in str(exc_info.value)


def test_valid_positive_window_scale_still_constructs_and_converts_correctly():
    mapper = ScreenToImageMapper(window_origin=(0, 0), window_scale=2.5)

    result = mapper.to_image(50, 25)

    assert result == ImagePosition(x=20.0, y=10.0)
