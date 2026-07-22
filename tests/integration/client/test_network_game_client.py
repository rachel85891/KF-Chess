"""Real, end-to-end integration tests for Stage B5's client-side
networking core (kungfu_chess/client/network/network_game_client.py) -
a REAL server (server/game_server.py's GameServer, real
ConnectionManager, real background tick loop) is started on an
OS-assigned free port, and a REAL NetworkGameClient connects to it for
every scenario below, mirroring Stage B1-B3's own "real server, real
client, no mocking" convention.

PLACED UNDER tests/integration/client/, NOT tests/integration/server/:
these tests validate the CLIENT package's OWN real behavior
(NetworkGameClient's threading/connect/send/poll/close contract) - a
distinct concern from tests/integration/server/, which validates the
server's own protocol correctness independent of any particular client
implementation. This mirrors the split this project already applies at
the unit level (client-owned tests under tests/unit/client/,
server-owned tests under tests/unit/server/) - now extended to
integration/, giving the client package its own integration-test home
alongside its own existing unit-test home, rather than folding
client-focused real-network tests into the server's own directory.

WHY THESE TESTS DON'T WRAP THE WHOLE SCENARIO IN ONE asyncio.run(...),
unlike every earlier stage's own network tests: NetworkGameClient's
entire PUBLIC contract (connect/send_move/poll_incoming/close) is
deliberately plain, synchronous, ordinary-thread-callable - that is
the whole point of Stage B5 (a synchronous GUI thread, in Stage B6,
must be able to call these methods directly, with no `await` anywhere
in its own frame loop). Testing it via `asyncio.run` would test a
DIFFERENT, easier calling convention than the one this class actually
promises. Instead, each test below is a plain synchronous `def
test_...()` that calls NetworkGameClient's real synchronous API
directly - exactly how a future GameLoopRunner will - while a REAL
server runs concurrently on ITS OWN separate background thread+event
loop (see _BackgroundTestServer, below), completely independent of
NetworkGameClient's own internal background thread. Two independent
real background threads/loops (server's own, and each
NetworkGameClient's own), driven by one synchronous test thread - the
same shape Stage B6's real client process will eventually have (one
synchronous GUI thread + one NetworkGameClient background thread; the
server being a separate OS process entirely, just simulated here via
its own thread for test convenience).
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

_JOIN_TIMEOUT_S = 5.0
_POLL_TIMEOUT_S = 5.0
_POLL_INTERVAL_S = 0.05


class _BackgroundTestServer:
    """Runs a real GameServer-backed websockets server on its OWN
    background thread + event loop - a real, separate process would be
    even more realistic, but a dedicated thread is the standard,
    already-established substitute for "a real server that just
    happens to be reachable" in this project's own test suite (mirrors
    every earlier stage's `_running_server`/`_running_game_server`
    helper, just adapted to run OUTSIDE the test's own event loop,
    since NetworkGameClient's tests are synchronous, not async, per
    this module's own docstring)."""

    def __init__(self) -> None:
        self.uri: str = ""
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
        game_server = GameServer()
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
        assert client1.connect(test_server.uri) == Color.WHITE
        assert client1.assigned_color == Color.WHITE

        assert client2.connect(test_server.uri) == Color.BLACK
        assert client2.assigned_color == Color.BLACK
    finally:
        client1.close()
        client2.close()
        test_server.stop()


def test_send_move_then_poll_eventually_surfaces_the_expected_broadcast():
    test_server = _BackgroundTestServer()
    client1 = NetworkGameClient()
    client2 = NetworkGameClient()
    try:
        assert client1.connect(test_server.uri) == Color.WHITE
        assert client2.connect(test_server.uri) == Color.BLACK

        client1.send_move(Color.WHITE, PieceKind.PAWN, Position(row=6, col=4), Position(row=4, col=4))

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
        assert client1.connect(test_server.uri) == Color.WHITE
        assert client2.connect(test_server.uri) == Color.BLACK

        client1.send_jump(Color.WHITE, PieceKind.ROOK, Position(row=7, col=0))

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
    try:
        assert client.connect(test_server.uri) == Color.WHITE

        # The server now sends one join-time board-state message right
        # after assigned_color (server/game_server.py's own initial-
        # board-state-on-join fix) - drain that one expected message
        # first (real delivery, so poll for it rather than assuming
        # it's already queued the instant connect() returns).
        _poll_until(client, lambda messages: len(messages) >= 1, _POLL_TIMEOUT_S)

        # Nothing else was sent by anyone - no further broadcast has
        # any reason to exist yet.
        assert client.poll_incoming() == []
        # Calling it again immediately must still be empty and must not
        # block or raise.
        assert client.poll_incoming() == []
    finally:
        client.close()
        test_server.stop()


def test_two_independent_clients_have_no_cross_talk_in_their_incoming_streams():
    test_server = _BackgroundTestServer()
    client1 = NetworkGameClient()
    client2 = NetworkGameClient()
    try:
        assert client1.connect(test_server.uri) == Color.WHITE
        assert client2.connect(test_server.uri) == Color.BLACK

        # Each client's own join-time board-state message (see above)
        # is expected and drained here first - the real thing being
        # proven below is that NEITHER client's stream contains
        # anything belonging to the OTHER (no cross-talk), not that
        # the stream is empty outright.
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
    try:
        assert client.connect(test_server.uri) == Color.WHITE
    finally:
        client.close()
        client.close()  # idempotent even after a real connection
        test_server.stop()
