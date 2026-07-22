"""Unit tests for Stage C1 ("Home Screen v1") - the shell-based
(plain text) login step that runs BEFORE the existing real GUI+network
client (NetworkGameLoopRunner) starts - kungfu_chess/client/
home_screen.py.

No real networking, no real GUI, no real stdin/stdout: every I/O
boundary this module has (reading a line, printing a line, connecting,
launching the GUI) is injected as a plain callable - see
home_screen.py's own module docstring for why this mirrors this
codebase's already-established "inject the thing that varies"
convention (e.g. NetworkGameLoopRunner's own injectable `clock`
parameter) rather than calling input()/print() or constructing a real
NetworkGameLoopRunner directly, which would make this logic untestable
without a real terminal/network/display.
"""

from __future__ import annotations

from kungfu_chess.client.home_screen import (
    SERVER_FULL_DISPLAY_MESSAGE,
    format_welcome_message,
    prompt_username,
    run_shell_login_and_launch,
)
from kungfu_chess.client.loop.network_game_loop_runner import ConnectionRejectedError
from kungfu_chess.model.color import Color


class _FakeIO:
    """A tiny, injectable stand-in for stdin/stdout: `input_fn` pops
    the next queued reply (raising if the test queued too few - a
    scenario driving this needs fixing, not silently hanging like a
    real blocking input() would), `output_fn` records every printed
    line in order."""

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.printed: list[str] = []

    def input_fn(self, prompt: str) -> str:
        self.printed.append(prompt)
        return self._replies.pop(0)

    def output_fn(self, text: str) -> None:
        self.printed.append(text)


def test_prompt_username_returns_the_first_non_empty_reply():
    io = _FakeIO(["Alice"])

    username = prompt_username(io.input_fn, io.output_fn)

    assert username == "Alice"


def test_prompt_username_re_prompts_on_a_blank_reply_then_accepts_the_next_one():
    io = _FakeIO(["", "Bob"])

    username = prompt_username(io.input_fn, io.output_fn)

    assert username == "Bob"
    # A message was shown between the two prompts explaining why the
    # first reply was rejected - not just a silent re-ask.
    assert any("empty" in line.lower() for line in io.printed)


def test_prompt_username_re_prompts_on_a_whitespace_only_reply():
    io = _FakeIO(["   ", "Carol"])

    username = prompt_username(io.input_fn, io.output_fn)

    assert username == "Carol"


def test_prompt_username_strips_surrounding_whitespace_from_an_accepted_reply():
    io = _FakeIO(["  Dave  "])

    username = prompt_username(io.input_fn, io.output_fn)

    assert username == "Dave"


def test_format_welcome_message_includes_the_given_username_and_the_real_assigned_color():
    assert format_welcome_message("Alice", Color.WHITE) == "Welcome, Alice! You are playing as WHITE."
    assert format_welcome_message("Bob", Color.BLACK) == "Welcome, Bob! You are playing as BLACK."


class _FakeRunner:
    """A tiny stand-in for a real NetworkGameLoopRunner - only the one
    attribute run_shell_login_and_launch actually reads (assigned_color)
    is present, so a test can prove this class never reaches into any
    other real GUI/network attribute before handing the runner off to
    launch_gui_fn."""

    def __init__(self, assigned_color: Color) -> None:
        self.assigned_color = assigned_color


def test_successful_login_connects_prints_the_correct_welcome_and_launches_the_gui():
    io = _FakeIO(["Alice"])
    fake_runner = _FakeRunner(Color.WHITE)
    connect_calls: list[str] = []
    launch_calls: list[object] = []

    def fake_connect(uri: str):
        connect_calls.append(uri)
        return fake_runner

    def fake_launch(runner: object) -> None:
        launch_calls.append(runner)

    run_shell_login_and_launch(
        "ws://localhost:8765",
        input_fn=io.input_fn,
        output_fn=io.output_fn,
        connect_fn=fake_connect,
        launch_gui_fn=fake_launch,
    )

    assert connect_calls == ["ws://localhost:8765"]
    assert launch_calls == [fake_runner]
    assert "Welcome, Alice! You are playing as WHITE." in io.printed


def test_server_full_response_shows_the_correct_message_and_never_launches_the_gui():
    io = _FakeIO(["Alice"])
    launch_calls: list[object] = []

    def rejecting_connect(uri: str):
        raise ConnectionRejectedError(f"server rejected this connection (server_full): {uri}")

    def fake_launch(runner: object) -> None:
        launch_calls.append(runner)

    run_shell_login_and_launch(
        "ws://localhost:8765",
        input_fn=io.input_fn,
        output_fn=io.output_fn,
        connect_fn=rejecting_connect,
        launch_gui_fn=fake_launch,
    )

    assert SERVER_FULL_DISPLAY_MESSAGE in io.printed
    assert launch_calls == []  # the GUI must never even be constructed/launched


def test_username_is_prompted_before_any_connection_attempt():
    # Proves the ORDER: prompting happens first, connecting happens
    # only after a username was actually obtained - not the reverse.
    order: list[str] = []
    io = _FakeIO(["Alice"])

    def recording_input(prompt: str) -> str:
        order.append("prompt")
        return io.input_fn(prompt)

    def fake_connect(uri: str):
        order.append("connect")
        return _FakeRunner(Color.WHITE)

    run_shell_login_and_launch(
        "ws://localhost:8765",
        input_fn=recording_input,
        output_fn=io.output_fn,
        connect_fn=fake_connect,
        launch_gui_fn=lambda runner: None,
    )

    assert order == ["prompt", "connect"]
