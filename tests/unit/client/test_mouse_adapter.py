from __future__ import annotations

import cv2
import pytest

from kungfu_chess.client.input.mouse_adapter import InvalidWindowNameError, MouseAdapter
from kungfu_chess.client.input.screen_mapper import ScreenToImageMapper
from kungfu_chess.model.position import Position


class SpyController:
    """A lightweight stand-in for the real Controller, used instead of
    a real Controller+GameEngine+Board: these tests exercise
    MouseAdapter's own translation responsibility (event -> mapped
    click call), not Controller's click-interpretation logic, which
    already has its own tests elsewhere."""

    def __init__(self):
        self.click_calls: list[tuple[int, int]] = []

    def click(self, x, y):
        self.click_calls.append((x, y))


class JumpSpy:
    """Records every cell on_jump_requested was called with."""

    def __init__(self):
        self.jump_calls: list[Position] = []

    def __call__(self, cell: Position) -> None:
        self.jump_calls.append(cell)


def test_left_button_down_maps_coordinates_and_calls_controller_click():
    # A real ScreenToImageMapper is used (not a fake): it's already a
    # pure, cheap, well-tested class (Stage 2/2b), so using the real
    # thing gives genuine end-to-end confidence in the mapping->click
    # pipeline rather than testing against a hand-faked stand-in.
    mapper = ScreenToImageMapper(window_origin=(10, 20), window_scale=2.0)
    controller = SpyController()
    adapter = MouseAdapter(mapper, controller)

    adapter.on_mouse_event(cv2.EVENT_LBUTTONDOWN, 110, 220, 0, None)

    # to_image: x=(110-10)/2=50.0, y=(220-20)/2=100.0
    assert controller.click_calls == [(50, 100)]


def test_non_left_button_down_events_do_not_call_controller_click():
    mapper = ScreenToImageMapper(window_origin=(0, 0), window_scale=1.0)
    controller = SpyController()
    adapter = MouseAdapter(mapper, controller)

    adapter.on_mouse_event(cv2.EVENT_MOUSEMOVE, 50, 50, 0, None)
    adapter.on_mouse_event(cv2.EVENT_RBUTTONDOWN, 50, 50, 0, None)
    adapter.on_mouse_event(cv2.EVENT_LBUTTONUP, 50, 50, 0, None)

    assert controller.click_calls == []


def test_right_button_down_calls_on_jump_requested_with_the_mapped_cell():
    mapper = ScreenToImageMapper(window_origin=(0, 0), window_scale=1.0)
    controller = SpyController()
    jump_spy = JumpSpy()
    adapter = MouseAdapter(mapper, controller, on_jump_requested=jump_spy)

    # identity mapper (origin 0, scale 1): image pixel (250, 150) ->
    # cell (row=150//CELL_SIZE=1, col=250//CELL_SIZE=2), CELL_SIZE=100.
    adapter.on_mouse_event(cv2.EVENT_RBUTTONDOWN, 250, 150, 0, None)

    assert jump_spy.jump_calls == [Position(row=1, col=2)]
    # right-click never touches Controller.click, even when a jump was
    # actually requested - the two gestures are fully separate paths.
    assert controller.click_calls == []


def test_right_button_down_without_on_jump_requested_is_a_safe_no_op():
    mapper = ScreenToImageMapper(window_origin=(0, 0), window_scale=1.0)
    controller = SpyController()
    adapter = MouseAdapter(mapper, controller)  # on_jump_requested defaults to None

    adapter.on_mouse_event(cv2.EVENT_RBUTTONDOWN, 250, 150, 0, None)  # no exception == success

    assert controller.click_calls == []


def test_left_button_down_behavior_is_unaffected_by_on_jump_requested_being_provided():
    # Confirms left-click/move behavior is provably unchanged even once
    # a jump callback is wired in - the two gestures must stay fully
    # independent.
    mapper = ScreenToImageMapper(window_origin=(10, 20), window_scale=2.0)
    controller = SpyController()
    jump_spy = JumpSpy()
    adapter = MouseAdapter(mapper, controller, on_jump_requested=jump_spy)

    adapter.on_mouse_event(cv2.EVENT_LBUTTONDOWN, 110, 220, 0, None)

    assert controller.click_calls == [(50, 100)]
    assert jump_spy.jump_calls == []


def test_attach_registers_on_mouse_event_via_cv2_set_mouse_callback(monkeypatch):
    mapper = ScreenToImageMapper(window_origin=(0, 0), window_scale=1.0)
    controller = SpyController()
    adapter = MouseAdapter(mapper, controller)

    recorded = {}

    def fake_set_mouse_callback(window_name, callback, param=None):
        recorded["window_name"] = window_name
        recorded["callback"] = callback

    monkeypatch.setattr(cv2, "setMouseCallback", fake_set_mouse_callback)

    adapter.attach("Kung Fu Chess")

    assert recorded["window_name"] == "Kung Fu Chess"
    assert recorded["callback"] == adapter.on_mouse_event


def test_attach_raises_invalid_window_name_error_for_empty_name():
    mapper = ScreenToImageMapper(window_origin=(0, 0), window_scale=1.0)
    controller = SpyController()
    adapter = MouseAdapter(mapper, controller)

    with pytest.raises(InvalidWindowNameError):
        adapter.attach("")
