"""home_screen.py: Stage C1 ("Home Screen v1") - a shell-based (plain
text, stdin/stdout - NOT a GUI screen) login step that runs BEFORE the
existing, already-working real GUI+network client
(kungfu_chess.client.loop.network_game_loop_runner.NetworkGameLoopRunner)
starts.

SCOPE - USERNAME IS COSMETIC ONLY AT THIS STAGE, DELIBERATELY: this is
the FIRST of several planned Home Screen stages (per the CTD26 slides'
own "Home Screen v1" framing) - password/SQLite-backed accounts/ELO
rating are all explicitly a SEPARATE, later stage (Stage D), not
attempted here. The username collected by prompt_username, below, is
used for exactly one thing - the local welcome message
(format_welcome_message) - and for nothing else: it is never sent to
the server in any wire message, never used to authenticate anything,
and never compared against any other player's username (there is no
uniqueness/persistence requirement at this stage at all). The
server's own color assignment (first connection is White, second is
Black - server/application/game_server.py's own already-existing,
unchanged `handle_connection`) has no knowledge this module even
exists; this module only ever READS `runner.assigned_color` AFTER
connecting, purely to decide what to print locally. A future Stage D
extending this same entry point would add real persistence/
authentication as a NEW step inserted between prompt_username and
connect_fn (e.g. "look up or create this username in SQLite, prompt
for + verify a password, compute an ELO-based matchmaking choice") -
everything below this docstring is written so that insertion needs no
change to run_shell_login_and_launch's own signature or control flow,
only a new function slotted into the same place prompt_username is
called from today.

WHY EVERY I/O BOUNDARY HERE IS AN INJECTED CALLABLE, NOT A DIRECT
input()/print() CALL: mirrors this codebase's own already-established
"inject the thing that varies" convention (e.g.
NetworkGameLoopRunner's own injectable `clock` parameter, Stage B7.5 -
see that class's own module docstring) rather than inventing a new
pattern for this stage alone. A direct `input()`/`print()` call would
make this module's own prompt/validation/welcome-message logic
impossible to unit-test without a real attached terminal; every public
function here instead takes plain `Callable[[str], str]` (`input_fn`)
and `Callable[[str], None]` (`output_fn`) parameters, defaulting to the
real `input`/`print` builtins for actual runtime use, and swappable for
a fake, recording stand-in in tests (see
tests/unit/client/test_home_screen.py) - the exact same DIP shape this
project already applies everywhere it has a real I/O boundary to keep
testable (GameSession/GameServer/ProtocolHandler's own constructor-
injected collaborators, server/application/game_session.py's own
`board: Optional[Board] = None`).

`connect_fn`/`launch_gui_fn` ARE INJECTED FOR THE SAME REASON, AND FOR
NOTHING NEW BEYOND IT: `connect_fn` defaults to `_default_connect`,
below, a tiny wrapper around the real NetworkGameLoopRunner class -
constructing one IS the exact, unmodified connection call
network_main.py already performs today (NetworkGameLoopRunner's own
__init__ owns and connects a real NetworkGameClient, raising
ConnectionRejectedError on "server_full" - see that class's own module
docstring). This module deliberately does NOT call
NetworkGameClient.connect() a second, separate time itself - doing so
would open a REDUNDANT second real connection instead of reusing the
one real connection this same process already needs for the GUI, and
would also duplicate NetworkGameLoopRunner's own already-correct
"server_full" detection instead of reusing it. `launch_gui_fn` defaults
to `_default_launch_gui`, below, which reproduces network_main.py's own
pre-existing `try: runner.run() finally: runner.close()` sequence
verbatim - the actual GUI/rendering code inside
NetworkGameLoopRunner.run() is completely untouched by this stage,
exactly as required. Both are injectable purely so
tests/unit/client/test_home_screen.py can substitute a fake connector
(one that raises ConnectionRejectedError, to prove the server_full
path never even attempts to launch a GUI) and a spy launcher (to prove
the real one WOULD have been launched, without actually opening a real
cv2 window/network connection in a unit test).

WHY `connect_fn` TAKES `(uri, username)`, NOT JUST `(uri)` (feature/
display-username-and-local-player-label): NetworkGameLoopRunner gained
its own optional `username` constructor parameter (see that class's own
module docstring's "USERNAME REACHES THE GUI" section) so the local
player's own panel can show their real name instead of a generic label
- but the username collected by prompt_username, below, is only ever
known INSIDE run_shell_login_and_launch, after connect_fn's own default
value was already bound at function-definition time. `_default_connect`
exists specifically so `username` can still reach the real
NetworkGameLoopRunner constructor AS a keyword argument (`username=
username`), never positionally - passing it positionally would risk
silently colliding with that class's own `window_name`/`headless`/
`clock` positional parameters instead of its `username` one.

SRP - THREE SEPARATE, INDEPENDENTLY TESTABLE UNITS, NOT ONE BLOCK:
`prompt_username` (validation/re-prompt logic only),
`format_welcome_message` (pure string formatting only), and
`run_shell_login_and_launch` (the thin orchestrator wiring the two
together with the injected connect/launch steps) - mirrors this
project's own "small classes/functions with separated responsibilities"
rule (docs/spec.md §1) applied to this module's own three genuinely
distinct concerns.
"""

from __future__ import annotations

from typing import Callable, Optional

from kungfu_chess.client.loop.network_game_loop_runner import ConnectionRejectedError, NetworkGameLoopRunner
from kungfu_chess.model.color import Color

InputFn = Callable[[str], str]
OutputFn = Callable[[str], None]
ConnectFn = Callable[[str, Optional[str]], NetworkGameLoopRunner]

USERNAME_PROMPT_TEXT = "Enter your username: "
_EMPTY_USERNAME_MESSAGE = "Username cannot be empty - please try again."
SERVER_FULL_DISPLAY_MESSAGE = "Server is full - only two players are supported right now."
_MOVE_INSTRUCTIONS = (
    "Left-click your own piece, then left-click a destination to move it.",
    "Press 'q' or close the window to quit.",
)


def prompt_username(input_fn: InputFn = input, output_fn: OutputFn = print) -> str:
    """Prompt for a username via `input_fn`, re-prompting for as long
    as the reply is blank (empty, or whitespace-only) - see module
    docstring's "SCOPE" section: no other validation (uniqueness,
    persistence, character restrictions) applies at this stage.

    Args:
        input_fn: Called with the prompt text, expected to return the
            raw reply string - defaults to the real `input` builtin.
        output_fn: Called with each line this function prints (the
            blank-reply rejection message only - the prompt text
            itself is `input_fn`'s own argument, not a separate
            output_fn call) - defaults to the real `print` builtin.

    Returns:
        The first reply whose stripped form is non-empty, itself
        stripped of leading/trailing whitespace (" Alice " and "Alice"
        are the same username for this cosmetic-only stage's purposes
        - see module docstring).
    """

    while True:
        raw_reply = input_fn(USERNAME_PROMPT_TEXT)
        username = raw_reply.strip()
        if username:
            return username
        output_fn(_EMPTY_USERNAME_MESSAGE)


def format_welcome_message(username: str, color: Color) -> str:
    """The local, human-readable welcome message shown once this
    client's assigned color is known.

    Args:
        username: The cosmetic-only username prompt_username collected
            (see module docstring's "SCOPE" section - never sent to
            the server, never used here for anything but this message).
        color: This connection's real, server-assigned Color
            (NetworkGameLoopRunner.assigned_color, set from the
            server's own real "assigned_color:<color>" join response).

    Returns:
        e.g. "Welcome, Alice! You are playing as WHITE." - `color.name`
        (the upper-case enum member name), not `color.value` (the
        terse wire letter "w"/"b" the protocol itself uses) - this
        message is for a human to read, matching
        ProtocolHandler.format_assigned_color's own identical
        "spelled out for a human, not the wire letter" choice.
    """

    return f"Welcome, {username}! You are playing as {color.name}."


def _default_connect(uri: str, username: Optional[str]) -> NetworkGameLoopRunner:
    """The real production connect_fn - see module docstring's "WHY
    `connect_fn` TAKES `(uri, username)`" section for why this tiny
    wrapper exists rather than passing NetworkGameLoopRunner itself as
    the default: `username` must reach that class's own constructor as
    a KEYWORD argument (never positionally, to avoid colliding with its
    `window_name`/`headless`/`clock` positional parameters)."""

    return NetworkGameLoopRunner(uri, username=username)


def _default_launch_gui(runner: NetworkGameLoopRunner) -> None:
    """The real production launch_gui_fn - reproduces
    network_main.py's own pre-existing `try: runner.run() finally:
    runner.close()` sequence verbatim (see module docstring's
    "`connect_fn`/`launch_gui_fn`..." section) - NetworkGameLoopRunner
    itself is completely unmodified by this stage."""

    try:
        runner.run()
    finally:
        runner.close()


def run_shell_login_and_launch(
    uri: str,
    *,
    input_fn: InputFn = input,
    output_fn: OutputFn = print,
    connect_fn: ConnectFn = _default_connect,
    launch_gui_fn: Callable[[NetworkGameLoopRunner], None] = _default_launch_gui,
) -> None:
    """The Stage C1 orchestrator: prompt for a username, THEN connect,
    THEN print a welcome message (or the server_full message), THEN
    launch the GUI - see module docstring for the full reasoning behind
    every injected parameter below.

    Args:
        uri: The WebSocket server URI to connect to - forwarded to
            connect_fn unchanged, never inspected here.
        input_fn: See prompt_username.
        output_fn: See prompt_username - also used for every other
            message this function itself prints (the "Connecting to
            ..." status line, the welcome/server_full message, and the
            move instructions).
        connect_fn: Called as `connect_fn(uri, username)`. Defaults to
            _default_connect - see module docstring for why constructing
            a real NetworkGameLoopRunner IS the exact, unmodified real
            connection call, not a second one, and why `username` is
            threaded through it (feature/display-username-and-local-
            player-label).
        launch_gui_fn: Defaults to _default_launch_gui - see module
            docstring.

    Returns:
        None.

    Order, and why it cannot be reordered (see module docstring's
    "SRP" section - this is the one place all four steps are wired
    together): a username is collected BEFORE any connection attempt
    (connect_fn needs it, per the "WHY `connect_fn` TAKES..." section),
    connecting happens next (the one point that can raise
    ConnectionRejectedError), and the welcome message can only be
    formatted AFTER a successful connect (it needs the real, server-
    assigned color - there is no color to report before that). A
    ConnectionRejectedError - the server's real "server_full" response,
    detected by NetworkGameLoopRunner's own __init__ - is caught here
    and shown via SERVER_FULL_DISPLAY_MESSAGE; launch_gui_fn is
    reached (and therefore ever called) only on the non-rejected path,
    per this stage's own explicit requirement that a rejected
    connection must never attempt to construct/launch a GUI.
    """

    username = prompt_username(input_fn, output_fn)

    output_fn(f"Connecting to {uri} ...")
    try:
        runner = connect_fn(uri, username)
    except ConnectionRejectedError:
        output_fn(SERVER_FULL_DISPLAY_MESSAGE)
        return

    output_fn(format_welcome_message(username, runner.assigned_color))
    for line in _MOVE_INSTRUCTIONS:
        output_fn(line)

    launch_gui_fn(runner)
    output_fn("Game loop ended.")
