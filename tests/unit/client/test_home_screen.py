"""Unit tests for the shell-based (plain text) login step that runs
BEFORE the existing real GUI+network client (NetworkGameLoopRunner)
starts - kungfu_chess/client/home_screen.py. Covers Stage C1 (username
prompt/welcome message) and Stage D2 (password prompt, real
authentication, rating display).

No real networking, no real GUI, no real stdin/stdout: every I/O
boundary this module has (reading a line, printing a line, connecting,
launching the GUI) is injected as a plain callable - see
home_screen.py's own module docstring for why this mirrors this
codebase's already-established "inject the thing that varies"
convention (e.g. NetworkGameLoopRunner's own injectable `clock`
parameter) rather than calling input()/print()/getpass.getpass() or
constructing a real NetworkGameLoopRunner directly, which would make
this logic untestable without a real terminal/network/display.
"""

from __future__ import annotations

from kungfu_chess.client.home_screen import (
    MATCHMAKING_TIMEOUT_DISPLAY_MESSAGE,
    SEARCHING_FOR_OPPONENT_DISPLAY_MESSAGE,
    SERVER_FULL_DISPLAY_MESSAGE,
    WRONG_PASSWORD_DISPLAY_MESSAGE,
    format_welcome_message,
    prompt_password,
    prompt_username,
    run_shell_login_and_launch,
)
from kungfu_chess.client.loop.network_game_loop_runner import ConnectionRejectedError
from kungfu_chess.model.color import Color


class _FakeIO:
    """A tiny, injectable stand-in for stdin/stdout/getpass: `input_fn`
    and `password_input_fn` both pop the next queued reply, in order,
    from the SAME underlying queue (raising if the test queued too few
    - a scenario driving this needs fixing, not silently hanging like a
    real blocking input()/getpass.getpass() would) - modeling the real,
    sequential "username prompt, then password prompt" order this
    module's own run_shell_login_and_launch always uses. `output_fn`
    records every printed line in order."""

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.printed: list[str] = []

    def input_fn(self, prompt: str) -> str:
        self.printed.append(prompt)
        return self._replies.pop(0)

    def password_input_fn(self, prompt: str) -> str:
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


def test_prompt_password_returns_the_first_non_empty_reply():
    io = _FakeIO(["correct horse battery staple"])

    password = prompt_password(io.password_input_fn, io.output_fn)

    assert password == "correct horse battery staple"


def test_prompt_password_re_prompts_on_a_blank_reply_then_accepts_the_next_one():
    io = _FakeIO(["", "hunter2"])

    password = prompt_password(io.password_input_fn, io.output_fn)

    assert password == "hunter2"
    assert any("empty" in line.lower() for line in io.printed)


def test_prompt_password_does_not_strip_surrounding_whitespace_unlike_prompt_username():
    # Whitespace can be a real, intentional part of a password - unlike
    # a cosmetic username, it must never be silently altered.
    io = _FakeIO(["  spacey password  "])

    password = prompt_password(io.password_input_fn, io.output_fn)

    assert password == "  spacey password  "


def test_format_welcome_message_includes_the_username_color_and_rating():
    assert (
        format_welcome_message("Alice", Color.WHITE, 1200) == "Welcome, Alice! You are playing as WHITE. Rating: 1200."
    )
    assert format_welcome_message("Bob", Color.BLACK, 1450) == "Welcome, Bob! You are playing as BLACK. Rating: 1450."


class _FakeRunner:
    """A tiny stand-in for a real NetworkGameLoopRunner - only the two
    attributes run_shell_login_and_launch actually reads
    (assigned_color, rating) are present, so a test can prove this
    class never reaches into any other real GUI/network attribute
    before handing the runner off to launch_gui_fn."""

    def __init__(self, assigned_color: Color, rating: int = 1200) -> None:
        self.assigned_color = assigned_color
        self.rating = rating


def test_successful_login_connects_with_the_collected_credentials_prints_the_correct_welcome_and_launches_the_gui():
    io = _FakeIO(["Alice", "correct horse battery staple"])
    fake_runner = _FakeRunner(Color.WHITE, rating=1200)
    connect_calls: list[tuple[str, object, object]] = []
    launch_calls: list[object] = []

    def fake_connect(uri: str, username: object, password: object, on_searching_for_opponent: object):
        connect_calls.append((uri, username, password))
        return fake_runner

    def fake_launch(runner: object) -> None:
        launch_calls.append(runner)

    run_shell_login_and_launch(
        "ws://localhost:8765",
        input_fn=io.input_fn,
        output_fn=io.output_fn,
        password_input_fn=io.password_input_fn,
        connect_fn=fake_connect,
        launch_gui_fn=fake_launch,
    )

    # connect_fn is called with the ACTUAL username AND password
    # prompt_username/prompt_password collected - not just the uri - so
    # NetworkGameLoopRunner's own username/password parameters can be
    # threaded through by the real _default_connect.
    assert connect_calls == [("ws://localhost:8765", "Alice", "correct horse battery staple")]
    assert launch_calls == [fake_runner]
    assert "Welcome, Alice! You are playing as WHITE. Rating: 1200." in io.printed


def test_server_full_response_shows_the_correct_message_and_never_launches_the_gui():
    io = _FakeIO(["Alice", "correct horse battery staple"])
    launch_calls: list[object] = []

    def rejecting_connect(uri: str, username: object, password: object, on_searching_for_opponent: object):
        raise ConnectionRejectedError(f"server rejected this connection (server_full): {uri}", reason="server_full")

    def fake_launch(runner: object) -> None:
        launch_calls.append(runner)

    run_shell_login_and_launch(
        "ws://localhost:8765",
        input_fn=io.input_fn,
        output_fn=io.output_fn,
        password_input_fn=io.password_input_fn,
        connect_fn=rejecting_connect,
        launch_gui_fn=fake_launch,
    )

    assert SERVER_FULL_DISPLAY_MESSAGE in io.printed
    assert launch_calls == []  # the GUI must never even be constructed/launched


def test_wrong_password_response_shows_the_correct_message_and_never_launches_the_gui():
    io = _FakeIO(["Alice", "wrong password"])
    launch_calls: list[object] = []

    def rejecting_connect(uri: str, username: object, password: object, on_searching_for_opponent: object):
        raise ConnectionRejectedError(f"server rejected this connection (wrong_password): {uri}", reason="wrong_password")

    def fake_launch(runner: object) -> None:
        launch_calls.append(runner)

    run_shell_login_and_launch(
        "ws://localhost:8765",
        input_fn=io.input_fn,
        output_fn=io.output_fn,
        password_input_fn=io.password_input_fn,
        connect_fn=rejecting_connect,
        launch_gui_fn=fake_launch,
    )

    assert WRONG_PASSWORD_DISPLAY_MESSAGE in io.printed
    assert SERVER_FULL_DISPLAY_MESSAGE not in io.printed  # never conflated with the OTHER rejection reason
    assert launch_calls == []


def test_matchmaking_timeout_response_shows_the_correct_message_and_never_launches_the_gui():
    io = _FakeIO(["Alice", "correct horse battery staple"])
    launch_calls: list[object] = []

    def rejecting_connect(uri: str, username: object, password: object, on_searching_for_opponent: object):
        raise ConnectionRejectedError(
            f"server rejected this connection (matchmaking_timeout): {uri}", reason="matchmaking_timeout"
        )

    def fake_launch(runner: object) -> None:
        launch_calls.append(runner)

    run_shell_login_and_launch(
        "ws://localhost:8765",
        input_fn=io.input_fn,
        output_fn=io.output_fn,
        password_input_fn=io.password_input_fn,
        connect_fn=rejecting_connect,
        launch_gui_fn=fake_launch,
    )

    assert MATCHMAKING_TIMEOUT_DISPLAY_MESSAGE in io.printed
    assert SERVER_FULL_DISPLAY_MESSAGE not in io.printed
    assert WRONG_PASSWORD_DISPLAY_MESSAGE not in io.printed
    assert launch_calls == []


def test_searching_for_opponent_callback_prints_the_correct_message_when_the_real_connect_fn_invokes_it():
    # connect_fn is handed a callback (mirrors the real _default_connect
    # -> NetworkGameLoopRunner -> NetworkGameClient chain) - this proves
    # run_shell_login_and_launch supplies one that prints the correct
    # message, and only when/if connect_fn actually calls it (real,
    # server-confirmed feedback - never printed eagerly beforehand).
    io = _FakeIO(["Alice", "correct horse battery staple"])

    def connect_that_reports_searching(uri: str, username: object, password: object, on_searching_for_opponent):
        on_searching_for_opponent()
        on_searching_for_opponent()  # a real server could send this more than once
        return _FakeRunner(Color.WHITE)

    run_shell_login_and_launch(
        "ws://localhost:8765",
        input_fn=io.input_fn,
        output_fn=io.output_fn,
        password_input_fn=io.password_input_fn,
        connect_fn=connect_that_reports_searching,
        launch_gui_fn=lambda runner: None,
    )

    assert io.printed.count(SEARCHING_FOR_OPPONENT_DISPLAY_MESSAGE) == 2


def test_username_then_password_are_prompted_before_any_connection_attempt():
    # Proves the ORDER: username, then password, then connecting - not
    # any other order.
    order: list[str] = []
    io = _FakeIO(["Alice", "correct horse battery staple"])

    def recording_input(prompt: str) -> str:
        order.append("username_prompt")
        return io.input_fn(prompt)

    def recording_password_input(prompt: str) -> str:
        order.append("password_prompt")
        return io.password_input_fn(prompt)

    def fake_connect(uri: str, username: object, password: object, on_searching_for_opponent: object):
        order.append("connect")
        return _FakeRunner(Color.WHITE)

    run_shell_login_and_launch(
        "ws://localhost:8765",
        input_fn=recording_input,
        output_fn=io.output_fn,
        password_input_fn=recording_password_input,
        connect_fn=fake_connect,
        launch_gui_fn=lambda runner: None,
    )

    assert order == ["username_prompt", "password_prompt", "connect"]
