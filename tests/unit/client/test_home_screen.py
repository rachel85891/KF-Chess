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
    ROOM_NOT_FOUND_DISPLAY_MESSAGE,
    SEARCHING_FOR_OPPONENT_DISPLAY_MESSAGE,
    SERVER_FULL_DISPLAY_MESSAGE,
    WRONG_PASSWORD_DISPLAY_MESSAGE,
    format_welcome_message,
    prompt_password,
    prompt_room_choice,
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


def test_format_welcome_message_produces_a_distinct_spectator_message_for_a_viewer():
    # Stage F7 - color is None for a viewer, distinct from a real
    # player's message, never "playing as None."
    message = format_welcome_message("Carol", None, None)

    assert message == "Welcome, Carol! You are watching this match as a spectator."
    assert "playing as" not in message
    assert "Rating" not in message


class _FakeRunner:
    """A tiny stand-in for a real NetworkGameLoopRunner - only the
    attributes run_shell_login_and_launch actually reads (assigned_color,
    rating, is_viewer) are present, so a test can prove this class never
    reaches into any other real GUI/network attribute before handing the
    runner off to launch_gui_fn."""

    def __init__(self, assigned_color: Color, rating: int = 1200, is_viewer: bool = False) -> None:
        self.assigned_color = assigned_color
        self.rating = rating
        self.is_viewer = is_viewer


def test_successful_login_connects_with_the_collected_credentials_prints_the_correct_welcome_and_launches_the_gui():
    io = _FakeIO(["Alice", "correct horse battery staple", "1"])
    fake_runner = _FakeRunner(Color.WHITE, rating=1200)
    connect_calls: list[tuple[str, object, object]] = []
    launch_calls: list[object] = []

    def fake_connect(
        uri: str, username: object, password: object, on_searching_for_opponent: object, room_choice: object,
        on_room_created: object,
    ):
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
    io = _FakeIO(["Alice", "correct horse battery staple", "1"])
    launch_calls: list[object] = []

    def rejecting_connect(
        uri: str, username: object, password: object, on_searching_for_opponent: object, room_choice: object,
        on_room_created: object,
    ):
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
    io = _FakeIO(["Alice", "wrong password", "1"])
    launch_calls: list[object] = []

    def rejecting_connect(
        uri: str, username: object, password: object, on_searching_for_opponent: object, room_choice: object,
        on_room_created: object,
    ):
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
    io = _FakeIO(["Alice", "correct horse battery staple", "1"])
    launch_calls: list[object] = []

    def rejecting_connect(
        uri: str, username: object, password: object, on_searching_for_opponent: object, room_choice: object,
        on_room_created: object,
    ):
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


def test_room_not_found_response_shows_the_correct_message_and_never_launches_the_gui():
    # Stage F7 - a real, new rejection reason (an unknown JOIN_ROOM
    # code, or a room whose host already vanished).
    io = _FakeIO(["Alice", "correct horse battery staple", "3", "NOPE00"])
    launch_calls: list[object] = []

    def rejecting_connect(
        uri: str, username: object, password: object, on_searching_for_opponent: object, room_choice: object,
        on_room_created: object,
    ):
        raise ConnectionRejectedError(f"server rejected this connection (room_not_found): {uri}", reason="room_not_found")

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

    assert ROOM_NOT_FOUND_DISPLAY_MESSAGE in io.printed
    assert launch_calls == []


def test_a_viewer_join_launches_the_gui_and_never_prints_move_instructions():
    # Stage F7 - a successful VIEWER join is NOT a rejection - the GUI
    # IS launched, but the (irrelevant, misleading) move instructions
    # are not printed for someone who cannot click.
    io = _FakeIO(["Carol", "correct horse battery staple", "3", "ABCDEF"])
    fake_runner = _FakeRunner(assigned_color=None, rating=None, is_viewer=True)
    launch_calls: list[object] = []

    def fake_connect(
        uri: str, username: object, password: object, on_searching_for_opponent: object, room_choice: object,
        on_room_created: object,
    ):
        return fake_runner

    run_shell_login_and_launch(
        "ws://localhost:8765",
        input_fn=io.input_fn,
        output_fn=io.output_fn,
        password_input_fn=io.password_input_fn,
        connect_fn=fake_connect,
        launch_gui_fn=launch_calls.append,
    )

    assert launch_calls == [fake_runner]
    assert "Welcome, Carol! You are watching this match as a spectator." in io.printed
    assert not any("left-click" in line.lower() for line in io.printed)


def test_searching_for_opponent_callback_prints_the_correct_message_when_the_real_connect_fn_invokes_it():
    # connect_fn is handed a callback (mirrors the real _default_connect
    # -> NetworkGameLoopRunner -> NetworkGameClient chain) - this proves
    # run_shell_login_and_launch supplies one that prints the correct
    # message, and only when/if connect_fn actually calls it (real,
    # server-confirmed feedback - never printed eagerly beforehand).
    io = _FakeIO(["Alice", "correct horse battery staple", "1"])

    def connect_that_reports_searching(
        uri: str, username: object, password: object, on_searching_for_opponent, room_choice: object,
        on_room_created: object,
    ):
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


def test_username_then_password_then_room_choice_are_prompted_before_any_connection_attempt():
    # Proves the ORDER: username, then password, then the room-choice
    # menu (Stage F7), then connecting - not any other order.
    order: list[str] = []
    io = _FakeIO(["Alice", "correct horse battery staple", "1"])

    def recording_input(prompt: str) -> str:
        # prompt_room_choice also uses input_fn (not a separate
        # parameter) - distinguish its call from prompt_username's by
        # the prompt text itself, exactly like recording_password_input
        # already distinguishes its own single responsibility.
        if "username" in prompt.lower():
            order.append("username_prompt")
        else:
            order.append("room_choice_prompt")
        return io.input_fn(prompt)

    def recording_password_input(prompt: str) -> str:
        order.append("password_prompt")
        return io.password_input_fn(prompt)

    def fake_connect(
        uri: str, username: object, password: object, on_searching_for_opponent: object, room_choice: object,
        on_room_created: object,
    ):
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

    assert order == ["username_prompt", "password_prompt", "room_choice_prompt", "connect"]


def test_prompt_room_choice_returns_play_for_choice_one():
    io = _FakeIO(["1"])

    assert prompt_room_choice(io.input_fn, io.output_fn) == "PLAY"


def test_prompt_room_choice_returns_create_room_for_choice_two():
    io = _FakeIO(["2"])

    assert prompt_room_choice(io.input_fn, io.output_fn) == "CREATE_ROOM"


def test_prompt_room_choice_prompts_a_second_time_for_the_room_code_on_choice_three():
    io = _FakeIO(["3", "ABCDEF"])

    assert prompt_room_choice(io.input_fn, io.output_fn) == "JOIN_ROOM:ABCDEF"


def test_prompt_room_choice_re_prompts_on_an_invalid_initial_choice():
    io = _FakeIO(["9", "bogus", "1"])

    assert prompt_room_choice(io.input_fn, io.output_fn) == "PLAY"
    assert any("invalid" in line.lower() for line in io.printed)


def test_prompt_room_choice_re_prompts_on_a_blank_room_code_after_choosing_join_room():
    io = _FakeIO(["3", "   ", "ABCDEF"])

    assert prompt_room_choice(io.input_fn, io.output_fn) == "JOIN_ROOM:ABCDEF"
    assert any("empty" in line.lower() for line in io.printed)
