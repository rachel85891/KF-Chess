"""Real, end-to-end integration tests for Stage B5's client-side
networking core (kungfu_chess/client/network/network_game_client.py) -
a REAL server (server/application/game_server.py's GameServer, real
ConnectionManager, real background tick loop) is started on an
OS-assigned free port, and a REAL NetworkGameClient connects to it for
every scenario below, mirroring Stage B1-B3's own "real server, real
client, no mocking" convention.

PLACED UNDER tests/integration/client/, NOT tests/integration/server/:
these tests validate the CLIENT package's OWN real behavior
(NetworkGameClient's threading/connect/send/poll/close contract) - a
distinct concern from tests/integration/server/, which validates the
server's own protocol correctness independent of any particular client
implementation.

WHY THESE TESTS DON'T WRAP THE WHOLE SCENARIO IN ONE asyncio.run(...),
unlike every earlier stage's own network tests: NetworkGameClient's
entire PUBLIC contract (connect/send_move/poll_incoming/close) is
deliberately plain, synchronous, ordinary-thread-callable. Instead, each
test below is a plain synchronous `def test_...()` that calls
NetworkGameClient's real synchronous API directly, while a REAL server
runs concurrently on ITS OWN separate background thread+event loop (see
_BackgroundTestServer, below).

UPDATED for Stage D2's real auth handshake: connect() now requires real
username/password arguments - GameServer itself constructed with
user_repository_db_path=":memory:" so no test here touches a real
database file.

UPDATED AGAIN for Stage E1's real matchmaking (feature/matchmaking-
elo-queue-e1, see server/application/game_server.py's own "STAGE E1 -
REAL MATCHMAKING..." docstring section): connect() no longer returns
near-instantly on its own - a connection now only receives its own
assigned_color once a rating-compatible opponent has ALSO joined the
matchmaking queue. Two clients that need to match EACH OTHER can
therefore no longer call connect() SEQUENTIALLY on the same test thread
(the first one's own connect() call would block forever waiting for a
compatible second party whose own connect() call hasn't even started
yet) - `_start_connect`, below, starts each one on its OWN background
thread instead, so both are genuinely in flight concurrently, mirroring
how two real, independent human players would actually connect. A test
that only cares about ONE client's own behavior still needs a REAL,
compatible second party concurrently waiting to unblock it at all -
`_connect_with_dummy_opponent` connects a throwaway, same-rated (both
are fresh accounts, always rating-compatible) dummy on a background
thread for exactly this purpose, then discards it once matched (nothing
else in these tests depends on the dummy staying connected - it exists
purely to satisfy real matchmaking's own "need two compatible players"
requirement, not to run gameplay of its own).
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
import websockets

from kungfu_chess.client.network.network_game_client import NetworkGameClient
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import MS_PER_SQUARE
from server.application.game_server import GameServer

# Marked slow: this file constructs a real, background-threaded/tasked
# server and relies on real wall-clock waiting (asyncio.sleep/time.sleep,
# real tick-loop cadence, or real network round trips) - excluded from
# `pytest -m "not slow"` for fast, deterministic day-to-day runs; still
# run in full via the dedicated slow/real-time pass.
pytestmark = pytest.mark.slow


_JOIN_TIMEOUT_S = 15.0
_POLL_TIMEOUT_S = 15.0
_POLL_INTERVAL_S = 0.05
# Stage G1 - client auto-reconnect (see network_game_client.py's own
# "STAGE G1" docstring section). Reconnect polling gets its own,
# slightly more generous timeout than _POLL_TIMEOUT_S: a real reconnect
# involves a real, second AUTH round trip (real PBKDF2-hashed login,
# server/persistence/user_repository.py's own deliberately-slow-by-design
# cost) PLUS a brand new TCP/WS connection, on top of whatever backoff
# delay NetworkGameClient's own _RECONNECT_BACKOFF_SCHEDULE_S imposes -
# mirrors test_disconnect_countdown_autoresign.py's own identical
# "_RECONNECT_COUNTDOWN_S needs real headroom" reasoning.
_RECONNECT_POLL_TIMEOUT_S = 15.0
# Short enough that NetworkGameClient's own first reconnect attempt
# (fired after its own first, 0.5s backoff step) always lands well AFTER
# this countdown has already expired server-side - proving the
# window-expired path, not racing it.
_SHORT_DISCONNECT_COUNTDOWN_S = 0.2
# Mirrors test_matchmaking_protocol.py's own established _SHORT_TIMEOUT_S
# precedent (1.0s) for keeping a real matchmaking-timeout wait fast.
_SHORT_MATCHMAKING_TIMEOUT_S = 1.0


class _BackgroundTestServer:
    """Runs a real GameServer-backed websockets server on its OWN
    background thread + event loop - a real, separate process would be
    even more realistic, but a dedicated thread is the standard,
    already-established substitute for "a real server that just
    happens to be reachable" in this project's own test suite."""

    def __init__(
        self,
        disconnect_countdown_s: float | None = None,
        matchmaking_timeout_s: float | None = None,
    ) -> None:
        self.uri: str = ""
        # Stage G1 - exposed so a reconnect test can both override Stage
        # E2's own real countdown/timeout constructor parameters (to
        # keep a countdown-expiry test fast, mirroring
        # test_disconnect_countdown_autoresign.py's own established
        # override convention) and inspect real server-side state
        # afterward (e.g. ConnectionManager's own real connection count,
        # to prove a rejected connect() never spawns a lingering
        # background reconnect attempt).
        self.game_server: GameServer | None = None
        self._disconnect_countdown_s = disconnect_countdown_s
        self._matchmaking_timeout_s = matchmaking_timeout_s
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready,), daemon=True)
        self._thread.start()
        if not ready.wait(timeout=_JOIN_TIMEOUT_S):
            raise RuntimeError("background test server failed to start in time")

    def _run(self, ready: threading.Event) -> None:
        asyncio.run(self._serve(ready))

    async def _serve(self, ready: threading.Event) -> None:
        # matchmaking_timeout_s left at its own real default (60s)
        # unless a test explicitly overrides it - every scenario below
        # that doesn't override it always provides a compatible opponent
        # (concurrently), so no such test ever needs to wait for or
        # exercise a timeout.
        kwargs: dict[str, float] = {}
        if self._disconnect_countdown_s is not None:
            kwargs["disconnect_countdown_s"] = self._disconnect_countdown_s
        if self._matchmaking_timeout_s is not None:
            kwargs["matchmaking_timeout_s"] = self._matchmaking_timeout_s
        game_server = GameServer(user_repository_db_path=":memory:", **kwargs)
        self.game_server = game_server
        server = await websockets.serve(game_server.handle_connection, "localhost", 0)
        tick_task = asyncio.create_task(game_server.run_tick_loop())
        port = server.sockets[0].getsockname()[1]
        self.uri = f"ws://localhost:{port}"
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        ready.set()

        await self._stop_event.wait()

        tick_task.cancel()
        server.close()
        await server.wait_closed()

    def stop(self) -> None:
        if self._loop is not None and self._stop_event is not None:
            self._loop.call_soon_threadsafe(self._stop_event.set)
        self._thread.join(timeout=_JOIN_TIMEOUT_S)


def _white_and_black(
    client1: NetworkGameClient, client2: NetworkGameClient
) -> tuple[NetworkGameClient, NetworkGameClient]:
    """Returns (white_client, black_client) given two clients that just
    matched each other. Color assignment is driven by MATCHMAKING QUEUE
    order (see MatchmakingQueue.find_match's own FIFO pairing strategy),
    NOT by which of these two background threads happens to finish
    connecting first - asyncio's own scheduling of the two concurrent
    handle_connection coroutines makes that race genuinely
    nondeterministic from a test's point of view, so no test may assume
    client1 is WHITE and client2 is BLACK; only that they get OPPOSITE
    colors."""

    assert {client1.assigned_color, client2.assigned_color} == {Color.WHITE, Color.BLACK}
    if client1.assigned_color == Color.WHITE:
        return client1, client2
    return client2, client1


def _start_connect(client: NetworkGameClient, uri: str, username: str, password: str) -> threading.Thread:
    """Start client.connect(...) on its own background thread - see
    module docstring's "UPDATED AGAIN for Stage E1..." section for why
    two clients that need to match each other can no longer connect()
    sequentially on the same test thread."""

    thread = threading.Thread(target=client.connect, args=(uri, username, password), daemon=True)
    thread.start()
    return thread


def _connect_with_dummy_opponent(client: NetworkGameClient, uri: str, username: str, password: str) -> NetworkGameClient:
    """Connect `client` alongside a throwaway, same-rated dummy
    opponent on a background thread - see module docstring's own
    reasoning. Returns the dummy NetworkGameClient so the caller can
    close it once done (harmless to leave connected too, but tidy
    cleanup avoids leaking a background thread past the end of the
    test)."""

    dummy = NetworkGameClient()
    dummy_thread = threading.Thread(
        target=dummy.connect, args=(uri, f"{username}_dummy_opponent", "dummy password"), daemon=True
    )
    dummy_thread.start()
    try:
        client.connect(uri, username, password)
    finally:
        dummy_thread.join(timeout=_JOIN_TIMEOUT_S)
    return dummy


def _poll_until(client: NetworkGameClient, predicate, timeout_s: float) -> list[str]:
    """Poll `client.poll_incoming()` repeatedly (real sleeps, real
    time) until `predicate(all_messages_so_far)` is True or
    `timeout_s` elapses - the synchronous-test equivalent of the
    async `asyncio.wait_for(client.recv(), ...)` pattern earlier
    stages' own async tests use, adapted for NetworkGameClient's
    plain, non-blocking poll_incoming()."""

    messages: list[str] = []
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        messages.extend(client.poll_incoming())
        if predicate(messages):
            return messages
        time.sleep(_POLL_INTERVAL_S)
    return messages


def test_connect_returns_the_correct_assigned_color_for_first_and_second_client():
    test_server = _BackgroundTestServer()
    client1 = NetworkGameClient()
    client2 = NetworkGameClient()
    try:
        thread1 = _start_connect(client1, test_server.uri, "client1", "password1")
        thread2 = _start_connect(client2, test_server.uri, "client2", "password2")
        thread1.join(timeout=_JOIN_TIMEOUT_S)
        thread2.join(timeout=_JOIN_TIMEOUT_S)

        # Two rating-compatible clients get matched into ONE game with
        # OPPOSITE colors - see _white_and_black's own docstring for why
        # this test no longer asserts WHICH of client1/client2 in
        # particular is WHITE.
        _white_and_black(client1, client2)
    finally:
        client1.close()
        client2.close()
        test_server.stop()


def test_send_move_then_poll_eventually_surfaces_the_expected_broadcast():
    test_server = _BackgroundTestServer()
    client1 = NetworkGameClient()
    client2 = NetworkGameClient()
    try:
        thread1 = _start_connect(client1, test_server.uri, "client1", "password1")
        thread2 = _start_connect(client2, test_server.uri, "client2", "password2")
        thread1.join(timeout=_JOIN_TIMEOUT_S)
        thread2.join(timeout=_JOIN_TIMEOUT_S)
        white_client, black_client = _white_and_black(client1, client2)

        white_client.send_move(Color.WHITE, PieceKind.PAWN, Position(row=6, col=4), Position(row=4, col=4))

        # Real wait for the real tick loop to advance real time far
        # enough for the 2-square motion to complete (2 * MS_PER_SQUARE
        # ms), exactly like B3's own protocol-wiring tests wait for the
        # PieceArrived broadcast, not just the immediate MoveAccepted
        # one.
        timeout_s = (2 * MS_PER_SQUARE) / 1000 + 3.0

        def has_arrival_broadcast(messages: list[str]) -> bool:
            # Stage B7 (server track) added a new, single-line wire-
            # format event message alongside every existing multi-line
            # board-text broadcast (kungfu_chess/notation/
            # game_event_wire_format.py) - poll_incoming() now returns a
            # mix of both message shapes, so a short message (too few
            # lines to be board text) is skipped here rather than
            # indexed blindly; this predicate is only ever looking for
            # the multi-line board-text broadcast anyway.
            lines_per_message = [msg.splitlines() for msg in messages]
            return any(len(lines) > 4 and lines[4].split()[4] == "wP" for lines in lines_per_message)

        messages1 = _poll_until(client1, has_arrival_broadcast, timeout_s)
        messages2 = _poll_until(client2, has_arrival_broadcast, timeout_s)

        assert has_arrival_broadcast(messages1)
        assert has_arrival_broadcast(messages2)
    finally:
        client1.close()
        client2.close()
        test_server.stop()


def test_send_jump_then_poll_eventually_surfaces_the_jump_landed_broadcast():
    test_server = _BackgroundTestServer()
    client1 = NetworkGameClient()
    client2 = NetworkGameClient()
    try:
        thread1 = _start_connect(client1, test_server.uri, "client1", "password1")
        thread2 = _start_connect(client2, test_server.uri, "client2", "password2")
        thread1.join(timeout=_JOIN_TIMEOUT_S)
        thread2.join(timeout=_JOIN_TIMEOUT_S)
        white_client, black_client = _white_and_black(client1, client2)

        white_client.send_jump(Color.WHITE, PieceKind.ROOK, Position(row=7, col=0))

        # Real wait for the real tick loop to advance real time far
        # enough for the jump's own real airborne duration
        # (MS_PER_SQUARE, extra/jump.py's own JUMP_DURATION_MS) to
        # elapse and its landing to broadcast - mirrors
        # test_send_move_then_poll_eventually_surfaces_the_expected_
        # broadcast's own structure exactly, for a jump instead of a
        # move.
        timeout_s = MS_PER_SQUARE / 1000 + 3.0

        def has_jump_landed_wire(messages: list[str]) -> bool:
            return any(msg.startswith("EVT:LANDED:") for msg in messages)

        messages1 = _poll_until(client1, has_jump_landed_wire, timeout_s)
        messages2 = _poll_until(client2, has_jump_landed_wire, timeout_s)

        assert has_jump_landed_wire(messages1)
        assert has_jump_landed_wire(messages2)
    finally:
        client1.close()
        client2.close()
        test_server.stop()


def test_poll_incoming_returns_an_empty_list_when_nothing_new_has_arrived():
    test_server = _BackgroundTestServer()
    client = NetworkGameClient()
    dummy = None
    try:
        dummy = _connect_with_dummy_opponent(client, test_server.uri, "client", "password")
        # Which of client/dummy gets WHITE vs BLACK is a race (see
        # _white_and_black's own docstring) - only the fact that a real
        # color was assigned at all matters here.
        assert client.assigned_color in (Color.WHITE, Color.BLACK)

        # The server sends one join-time board-state message right
        # after assigned_color - drain that one expected message first
        # (real delivery, so poll for it rather than assuming it's
        # already queued the instant connect() returns).
        _poll_until(client, lambda messages: len(messages) >= 1, _POLL_TIMEOUT_S)

        # Nothing else was sent by anyone - no further broadcast has
        # any reason to exist yet.
        assert client.poll_incoming() == []
        # Calling it again immediately must still be empty and must not
        # block or raise.
        assert client.poll_incoming() == []
    finally:
        client.close()
        if dummy is not None:
            dummy.close()
        test_server.stop()


def test_two_independent_clients_have_no_cross_talk_in_their_incoming_streams():
    test_server = _BackgroundTestServer()
    client1 = NetworkGameClient()
    client2 = NetworkGameClient()
    try:
        thread1 = _start_connect(client1, test_server.uri, "client1", "password1")
        thread2 = _start_connect(client2, test_server.uri, "client2", "password2")
        thread1.join(timeout=_JOIN_TIMEOUT_S)
        thread2.join(timeout=_JOIN_TIMEOUT_S)
        _white_and_black(client1, client2)

        # Each client's own join-time board-state message is expected
        # and drained here first - the real thing being proven below is
        # that NEITHER client's stream contains anything belonging to
        # the OTHER (no cross-talk), not that the stream is empty
        # outright.
        _poll_until(client1, lambda messages: len(messages) >= 1, _POLL_TIMEOUT_S)
        _poll_until(client2, lambda messages: len(messages) >= 1, _POLL_TIMEOUT_S)

        # Neither client has sent a move - each one's own incoming
        # stream must independently have nothing further; one client's
        # queue is never affected by the other's.
        assert client1.poll_incoming() == []
        assert client2.poll_incoming() == []
    finally:
        client1.close()
        client2.close()
        test_server.stop()


def test_close_is_safe_even_if_connect_was_never_called():
    client = NetworkGameClient()

    client.close()  # must not hang or raise

    client.close()  # a second call must also be safe (idempotent)


def test_close_after_a_real_connect_is_safe_and_does_not_hang():
    test_server = _BackgroundTestServer()
    client = NetworkGameClient()
    dummy = None
    try:
        dummy = _connect_with_dummy_opponent(client, test_server.uri, "client", "password")
        assert client.assigned_color in (Color.WHITE, Color.BLACK)
    finally:
        client.close()
        client.close()  # idempotent even after a real connection
        if dummy is not None:
            dummy.close()
        test_server.stop()


def _start_connect_with_room_choice(
    client: NetworkGameClient, uri: str, username: str, password: str, room_choice: str, on_room_created=None
) -> threading.Thread:
    """Mirrors _start_connect's own shape exactly, extended with the
    real room_choice/on_room_created parameters this stage adds (Stage
    F7) - a host waits synchronously for a real guest to join, so this
    also needs its own background thread, exactly like two matchmaking
    clients waiting on each other already do."""

    thread = threading.Thread(
        target=client.connect,
        args=(uri, username, password, None, room_choice),
        kwargs={"on_room_created": on_room_created},
        daemon=True,
    )
    thread.start()
    return thread


def test_create_room_then_join_room_matches_host_and_guest_with_real_colors():
    test_server = _BackgroundTestServer()
    host = NetworkGameClient()
    guest = NetworkGameClient()
    created_codes: list[str] = []
    try:
        host_thread = _start_connect_with_room_choice(
            host, test_server.uri, "alice", "password1", "CREATE_ROOM", on_room_created=created_codes.append
        )
        # Give the host's own background thread a real moment to reach
        # room_created before asserting on it - the host is otherwise
        # still blocked waiting for a guest at this exact point.
        deadline = time.perf_counter() + _JOIN_TIMEOUT_S
        while not created_codes and time.perf_counter() < deadline:
            time.sleep(_POLL_INTERVAL_S)

        assert created_codes  # on_room_created fired with a real code
        code = created_codes[0]
        assert host.room_code == code

        guest_thread = _start_connect_with_room_choice(
            guest, test_server.uri, "bob", "password2", f"JOIN_ROOM:{code}"
        )
        host_thread.join(timeout=_JOIN_TIMEOUT_S)
        guest_thread.join(timeout=_JOIN_TIMEOUT_S)

        # Host=White, Guest=Black - see server/application/
        # game_server.py's own "STAGE F4" docstring section.
        assert host.assigned_color is Color.WHITE
        assert guest.assigned_color is Color.BLACK
        assert host.is_viewer is False
        assert guest.is_viewer is False
        assert guest.rejection_reason is None
    finally:
        host.close()
        guest.close()
        test_server.stop()


def test_a_third_join_room_on_a_full_room_becomes_a_viewer_not_a_rejection():
    test_server = _BackgroundTestServer()
    host = NetworkGameClient()
    guest = NetworkGameClient()
    viewer = NetworkGameClient()
    created_codes: list[str] = []
    try:
        host_thread = _start_connect_with_room_choice(
            host, test_server.uri, "alice", "password1", "CREATE_ROOM", on_room_created=created_codes.append
        )
        deadline = time.perf_counter() + _JOIN_TIMEOUT_S
        while not created_codes and time.perf_counter() < deadline:
            time.sleep(_POLL_INTERVAL_S)
        code = created_codes[0]

        guest_thread = _start_connect_with_room_choice(
            guest, test_server.uri, "bob", "password2", f"JOIN_ROOM:{code}"
        )
        host_thread.join(timeout=_JOIN_TIMEOUT_S)
        guest_thread.join(timeout=_JOIN_TIMEOUT_S)

        # A THIRD connection, joining the now-full room - a real
        # success (viewer), never a rejection (see _JoinResponse's own
        # docstring for why `assigned_color is None` alone can never
        # tell the two apart).
        viewer.connect(test_server.uri, "carol", "password3", room_choice=f"JOIN_ROOM:{code}")

        assert viewer.is_viewer is True
        assert viewer.assigned_color is None
        assert viewer.rejection_reason is None
    finally:
        host.close()
        guest.close()
        viewer.close()
        test_server.stop()


def test_join_room_on_an_unknown_code_is_a_real_rejection_not_a_viewer():
    test_server = _BackgroundTestServer()
    client = NetworkGameClient()
    try:
        client.connect(test_server.uri, "alice", "password1", room_choice="JOIN_ROOM:NOPE00")

        assert client.rejection_reason == "room_not_found"
        assert client.is_viewer is False
        assert client.assigned_color is None
    finally:
        client.close()
        test_server.stop()


def _force_close_connection(client: NetworkGameClient) -> None:
    """Simulate a real, ABRUPT mid-match drop of `client`'s CURRENT
    connection - closes the underlying TRANSPORT directly, bypassing
    the real WebSocket closing handshake a graceful client.close() (or
    NetworkGameClient.close()) would perform, mirroring
    tests/integration/server/test_ws_skeleton.py's own established
    "abrupt disconnect" technique exactly (re-verified directly against
    the installed websockets version before writing this: a graceful
    close produces ConnectionClosedOK, which websockets' own __aiter__
    implementation swallows silently - ending the `async for` loop with
    no exception at all - rather than raising, so _receive_loop would
    never even see it; only this abrupt, transport-level technique
    produces the genuine ConnectionClosedError a real network drop
    would, which is what actually exercises Stage G1's new reconnect
    logic). Scheduled onto `client`'s OWN background loop - a plain,
    non-coroutine callback (transport.close() is synchronous), not a
    coroutine needing run_coroutine_threadsafe."""

    client._loop.call_soon_threadsafe(client._connection.transport.close)


def test_client_automatically_reconnects_after_connection_drops_mid_match():
    test_server = _BackgroundTestServer()
    client1 = NetworkGameClient()
    client2 = NetworkGameClient()
    try:
        thread1 = _start_connect(client1, test_server.uri, "client1", "password1")
        thread2 = _start_connect(client2, test_server.uri, "client2", "password2")
        thread1.join(timeout=_JOIN_TIMEOUT_S)
        thread2.join(timeout=_JOIN_TIMEOUT_S)
        white_client, black_client = _white_and_black(client1, client2)
        original_color = white_client.assigned_color
        original_connection = white_client._connection

        _force_close_connection(white_client)

        deadline = time.perf_counter() + _RECONNECT_POLL_TIMEOUT_S
        while time.perf_counter() < deadline:
            if white_client._connection is not None and white_client._connection is not original_connection:
                break
            time.sleep(_POLL_INTERVAL_S)

        assert white_client._connection is not None
        assert white_client._connection is not original_connection
        assert white_client.assigned_color == original_color
    finally:
        client1.close()
        client2.close()
        test_server.stop()


def test_client_reconnecting_within_the_real_disconnect_countdown_resumes_the_same_match_and_notifies_opponent():
    # Deliberately uses the server's own real, UNMODIFIED
    # DEFAULT_DISCONNECT_COUNTDOWN_S (20 real seconds, never overridden
    # here) - NetworkGameClient's own backoff (first attempt at 0.5s)
    # reconnects far sooner than that, proving a real reconnect resumes
    # the SAME match/color well within the real production window, not
    # merely a test-shortened one.
    test_server = _BackgroundTestServer()
    client1 = NetworkGameClient()
    client2 = NetworkGameClient()
    try:
        thread1 = _start_connect(client1, test_server.uri, "client1", "password1")
        thread2 = _start_connect(client2, test_server.uri, "client2", "password2")
        thread1.join(timeout=_JOIN_TIMEOUT_S)
        thread2.join(timeout=_JOIN_TIMEOUT_S)
        white_client, black_client = _white_and_black(client1, client2)
        original_color = white_client.assigned_color
        original_connection = white_client._connection

        # Drain each client's own join-time board-state message first -
        # mirrors every other test in this file's own established
        # convention - so the opponent_reconnected assertion below can't
        # be accidentally satisfied by an unrelated, leftover message.
        _poll_until(black_client, lambda messages: len(messages) >= 1, _POLL_TIMEOUT_S)

        _force_close_connection(white_client)

        deadline = time.perf_counter() + _RECONNECT_POLL_TIMEOUT_S
        while time.perf_counter() < deadline:
            if white_client._connection is not None and white_client._connection is not original_connection:
                break
            time.sleep(_POLL_INTERVAL_S)

        assert white_client._connection is not original_connection
        assert white_client.assigned_color == original_color

        messages = _poll_until(
            black_client,
            lambda msgs: any(msg == "opponent_reconnected" for msg in msgs),
            _RECONNECT_POLL_TIMEOUT_S,
        )
        assert any(msg == "opponent_reconnected" for msg in messages)
    finally:
        client1.close()
        client2.close()
        test_server.stop()


def test_reconnect_surfaces_matchmaking_timeout_once_the_real_countdown_window_has_expired():
    test_server = _BackgroundTestServer(
        disconnect_countdown_s=_SHORT_DISCONNECT_COUNTDOWN_S,
        matchmaking_timeout_s=_SHORT_MATCHMAKING_TIMEOUT_S,
    )
    client1 = NetworkGameClient()
    client2 = NetworkGameClient()
    try:
        thread1 = _start_connect(client1, test_server.uri, "client1", "password1")
        thread2 = _start_connect(client2, test_server.uri, "client2", "password2")
        thread1.join(timeout=_JOIN_TIMEOUT_S)
        thread2.join(timeout=_JOIN_TIMEOUT_S)
        white_client, black_client = _white_and_black(client1, client2)

        _force_close_connection(white_client)

        # By the time NetworkGameClient's own first reconnect attempt
        # fires (0.5s backoff), _SHORT_DISCONNECT_COUNTDOWN_S has already
        # elapsed server-side, so the resume lookup finds nothing and
        # this reconnect attempt falls through to ORDINARY matchmaking
        # with white_client's own stored room_choice ("PLAY" - no other
        # compatible player is waiting) - which then times out via the
        # PRE-EXISTING matchmaking-timeout mechanism, surfacing as an
        # ordinary rejection - no new wire message needed (see
        # network_game_client.py's own "STAGE G1" docstring section).
        deadline = time.perf_counter() + _RECONNECT_POLL_TIMEOUT_S
        while white_client.rejection_reason is None and time.perf_counter() < deadline:
            time.sleep(_POLL_INTERVAL_S)

        assert white_client.rejection_reason == "matchmaking_timeout"
        assert white_client.assigned_color is None
    finally:
        client1.close()
        client2.close()
        test_server.stop()


def test_create_room_client_reconnect_after_countdown_expiry_replays_create_room_not_a_hardcoded_play():
    test_server = _BackgroundTestServer(disconnect_countdown_s=_SHORT_DISCONNECT_COUNTDOWN_S)
    host = NetworkGameClient()
    guest = NetworkGameClient()
    guest2 = NetworkGameClient()
    created_codes: list[str] = []
    try:
        host_thread = _start_connect_with_room_choice(
            host, test_server.uri, "alice", "password1", "CREATE_ROOM", on_room_created=created_codes.append
        )
        deadline = time.perf_counter() + _JOIN_TIMEOUT_S
        while not created_codes and time.perf_counter() < deadline:
            time.sleep(_POLL_INTERVAL_S)
        assert created_codes
        first_code = created_codes[0]

        guest_thread = _start_connect_with_room_choice(
            guest, test_server.uri, "bob", "password2", f"JOIN_ROOM:{first_code}"
        )
        host_thread.join(timeout=_JOIN_TIMEOUT_S)
        guest_thread.join(timeout=_JOIN_TIMEOUT_S)
        assert host.assigned_color is Color.WHITE
        assert guest.assigned_color is Color.BLACK

        _force_close_connection(host)

        # Past the SHORT countdown, the resume window has already
        # expired - the host's own STORED room_choice ("CREATE_ROOM", not
        # "PLAY") must be replayed verbatim: a SECOND on_room_created
        # callback firing (a second, real, DIFFERENT room code) is only
        # possible if "CREATE_ROOM" was genuinely resent - a hardcoded
        # "PLAY" default would instead silently enter ordinary
        # matchmaking and never call on_room_created again at all.
        deadline = time.perf_counter() + _RECONNECT_POLL_TIMEOUT_S
        while len(created_codes) < 2 and time.perf_counter() < deadline:
            time.sleep(_POLL_INTERVAL_S)

        assert len(created_codes) >= 2
        second_code = created_codes[1]
        assert second_code != first_code

        # Prove the new room is real and joinable - this also completes
        # the host's own in-flight reconnect attempt fully (rather than
        # leaving it parked waiting forever for a guest), so close()
        # below has nothing left in flight to race with.
        guest2_thread = _start_connect_with_room_choice(
            guest2, test_server.uri, "carol", "password3", f"JOIN_ROOM:{second_code}"
        )
        guest2_thread.join(timeout=_JOIN_TIMEOUT_S)
        assert guest2.assigned_color is Color.BLACK

        deadline = time.perf_counter() + _JOIN_TIMEOUT_S
        while host.assigned_color is not Color.WHITE and time.perf_counter() < deadline:
            time.sleep(_POLL_INTERVAL_S)
        assert host.assigned_color is Color.WHITE
    finally:
        host.close()
        guest.close()
        guest2.close()
        test_server.stop()


def test_a_rejected_connect_never_triggers_a_background_reconnect_loop():
    test_server = _BackgroundTestServer()
    client = NetworkGameClient()
    try:
        client.connect(test_server.uri, "alice", "password1", room_choice="JOIN_ROOM:NOPE00")
        assert client.rejection_reason == "room_not_found"

        # A naive reconnect implementation would treat the server
        # closing this already-rejected connection as "the connection
        # dropped, retry" and spin up an endless background AUTH loop
        # replaying the SAME rejected room choice forever -
        # _receive_loop's own guard (only ever reconnect while
        # self.rejection_reason is still None) exists specifically to
        # prevent this - see network_game_client.py's own "STAGE G1"
        # docstring section. Real wait, comfortably longer than the
        # first backoff step (0.5s), then confirm no new connection was
        # ever opened and rejection_reason was never overwritten.
        time.sleep(1.5)

        assert client.rejection_reason == "room_not_found"
        assert client.assigned_color is None
        assert test_server.game_server is not None
        assert test_server.game_server._connection_manager.connection_count == 0
    finally:
        client.close()
        test_server.stop()
