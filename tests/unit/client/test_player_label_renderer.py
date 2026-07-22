"""Unit tests for kungfu_chess/client/ui/player_label_renderer.py -
format_player_label's own dedicated, pure string-formatting tests (no
rendering, no Img at all - per this project's own established
convention, see tests/unit/client/test_captured_pieces_renderer.py's
own identical "pure function tests, plus a light rendering smoke test"
split), plus a smoke test proving render() itself does not raise
against a real Img canvas.
"""

from __future__ import annotations

from kungfu_chess.client.surface.img import Img
from kungfu_chess.client.ui.player_label_renderer import PlayerLabelRenderer, format_player_label
from kungfu_chess.model.color import Color


def test_local_player_with_a_username_is_labeled_with_their_name_and_you_and_their_real_color():
    assert format_player_label("Alice", Color.WHITE, is_local_player=True) == "Alice (You) - White"
    assert format_player_label("Bob", Color.BLACK, is_local_player=True) == "Bob (You) - Black"


def test_local_player_with_no_username_falls_back_to_a_generic_you_label():
    # Backward compatibility: NetworkGameLoopRunner's own `username`
    # constructor parameter defaults to None (e.g. existing headless
    # test construction that never passed one) - this must not crash
    # or render "None" literally.
    assert format_player_label(None, Color.WHITE, is_local_player=True) == "You - White"


def test_opponent_is_always_labeled_generically_regardless_of_the_local_username():
    # The opponent's real username is never transmitted by the wire
    # protocol at this stage (see home_screen.py's own "SCOPE" section)
    # - passing a username here at all would be a caller bug, but this
    # function must still never invent or leak it into the opponent's
    # own label.
    assert format_player_label("Alice", Color.BLACK, is_local_player=False) == "Opponent - Black"
    assert format_player_label(None, Color.WHITE, is_local_player=False) == "Opponent - White"


def test_render_does_not_raise_for_a_local_player_with_a_username():
    canvas = Img.blank_canvas(400, 400)
    renderer = PlayerLabelRenderer(canvas)

    renderer.render(x=0, color=Color.WHITE, username="Alice", is_local_player=True)


def test_render_does_not_raise_for_the_opponent():
    canvas = Img.blank_canvas(400, 400)
    renderer = PlayerLabelRenderer(canvas)

    renderer.render(x=180, color=Color.BLACK, username=None, is_local_player=False)


def test_render_does_not_raise_when_username_is_none_for_the_local_player():
    canvas = Img.blank_canvas(400, 400)
    renderer = PlayerLabelRenderer(canvas)

    renderer.render(x=0, color=Color.WHITE, username=None, is_local_player=True)
