from __future__ import annotations

import cv2
import pytest

from kungfu_chess.client.input.mouse_adapter import InvalidWindowNameError, MouseAdapter
from kungfu_chess.client.input.screen_mapper import ScreenToImageMapper


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
