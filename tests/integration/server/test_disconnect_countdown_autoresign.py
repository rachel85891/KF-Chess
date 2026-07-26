"""Real, end-to-end integration tests for Stage E2's disconnect-
countdown/auto-resign feature (server/application/game_server.py's own
new "STAGE E2" docstring section) - a REAL server (real GameServer,
real MatchmakingQueue, real per-match GameSession, real background tick
loop) and REAL websockets clients, mirroring
tests/integration/server/test_matchmaking_protocol.py's own "real
server, real client, no mocking" convention and its own concurrent-join
helper shape exactly.

WHY disconnect_countdown_s IS OVERRIDDEN TO A SHORT VALUE IN EVERY
SCENARIO BELOW THAT ACTUALLY WAITS FOR IT: mirrors Stage E1's own
established `matchmaking_timeout_s` override precedent
(test_matchmaking_protocol.py's own module docstring / _SHORT_TIMEOUT_S)
- no test here ever waits out a real 20-second countdown.

WHY A DISCONNECT IS SIMULATED VIA A REAL `client.close()`/transport
close, NEVER A MOCK: mirrors this project's own established "real
server, real client, no mocking" convention throughout the server
track (e.g. tests/integration/server/test_ws_skeleton.py's own
abrupt-disconnect test) - a real WebSocket close is the only genuine
way to trigger GameServer's own real ConnectionClosed handling path.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
import websockets

from kungfu_chess.notation.auth_command_format import format_auth_command
from kungfu_chess.notation.game_event_wire_format import EVENT_MESSAGE_PREFIX, parse_game_event
from server.application.game_server import GameServer
from server.presentation.protocol_handler import SEARCHING_FOR_OPPONENT_MESSAGE

# Marked slow: this file constructs a real, background-threaded/tasked
# server and relies on real wall-clock waiting (asyncio.sleep/time.sleep,
# real tick-loop cadence, or real network round trips) - excluded from
# `pytest -m "not slow"` for fast, deterministic day-to-day runs; still
# run in full via the dedicated slow/real-time pass.
pytestmark = pytest.mark.slow


_RECV_TIMEOUT_S = 20.0
_SHORT_COUNTDOWN_S = 1.0
_REACTION_DELAY_S = 0.3  # a real moment for the server's own coroutine to react to a disconnect
# The reconnect scenario needs real headroom beyond the bare countdown
# window: a real reconnect goes through a real, second AUTH round trip
# (real PBKDF2-hashed login, server/persistence/user_repository.py's own
# deliberately-slow-by-design cost) PLUS opening a brand new TCP/WS
# connection - a bare 1-second window (fine for the pure-expiry
# scenario below, which involves no second connection attempt at all)
# was found to occasionally race the real auto-resign under real
# system load (re-verified directly: this same flakiness reproduces
# identically with or without feature/elo-rating-update-d3's own
# changes present - a pre-existing timing margin issue, not a
# regression that stage introduced, flagged and fixed here since it was
# discovered while validating that stage's own tests).
_RECONNECT_COUNTDOWN_S = 6.0


@asynccontextmanager
async def _running_game_server(disconnect_countdown_s: float = 20.0):
    game_server = GameServer(user_repository_db_path=":memory:", disconnect_countdown_s=disconnect_countdown_s)
    server = await websockets.serve(game_server.handle_connection, "localhost", 0)
    tick_task = asyncio.create_task(game_server.run_tick_loop())
    try:
        port = server.sockets[0].getsockname()[1]
        yield f"ws://localhost:{port}", game_server
    finally:
        tick_task.cancel()
        try:
            await tick_task
        except asyncio.CancelledError:
            pass

        # A scenario that deliberately never lets a real disconnect
        # countdown resolve (e.g. proving the game isn't over yet,
        # without waiting the full window out), or that closes a
        # connection right at the very end of its own scenario body
        # (its own handle_connection coroutine may not have even
        # reached _handle_active_match_disconnect yet - a genuine
        # scheduling race, not something a single "resolve every
        # currently-pending future" pass before close() can reliably
        # catch), would otherwise leave that connection's own
        # handle_connection coroutine parked forever at `await
        # resolution` (see GameServer's own _handle_active_match_
        # disconnect docstring) - websockets' own Server.wait_closed()
        # waits for every such in-flight handler task to actually
        # finish, not just for sockets to close, so it could hang here
        # forever. The real production server (server/main.py) never
        # calls wait_closed() at all (it runs serve_forever() until the
        # process itself is killed) - this is a test-teardown-only
        # concern, fixed by bounding the wait: a lingering handler task
        # left over from a scenario that intentionally never resolved
        # its own countdown is harmless to abandon once the test itself
        # has already gotten everything it needs.
        server.close()
        try:
            await asyncio.wait_for(server.wait_closed(), timeout=2.0)
        except asyncio.TimeoutError:
            pass


def _parse_assigned_color_and_rating(message: str) -> tuple[str, int]:
    _, color_name, rating_text = message.split(":", 2)
    return color_name, int(rating_text)


async def _join_and_await_match(uri: str, username: str, password: str):
    """Connect, authenticate, drain searching_for_opponent, and return
    (connection, color_name, rating, board_text) once matched - mirrors
    test_matchmaking_protocol.py's own _join_and_await_outcome, extended
    to also drain the join-time board-state message (every scenario
    below needs a real, active match, never just the matchmaking
    outcome alone)."""

    client = await websockets.connect(uri)
    await client.send(format_auth_command(username, password))
    searching = await asyncio.wait_for(client.recv(), timeout=_RECV_TIMEOUT_S)
    assert searching == SEARCHING_FOR_OPPONENT_MESSAGE
    welcome = await asyncio.wait_for(client.recv(), timeout=_RECV_TIMEOUT_S)
    color_name, rating = _parse_assigned_color_and_rating(welcome)
    board_text = await asyncio.wait_for(client.recv(), timeout=_RECV_TIMEOUT_S)
    return client, color_name, rating, board_text


def test_a_disconnect_during_an_active_match_does_not_immediately_end_the_game_and_notifies_the_opponent():
    async def scenario():
        async with _running_game_server(disconnect_countdown_s=_SHORT_COUNTDOWN_S) as (uri, _game_server):
            (client_a, color_a, _rating_a, _board_a), (client_b, color_b, _rating_b, _board_b) = await asyncio.gather(
                _join_and_await_match(uri, "alice", "correct horse battery staple"),
                _join_and_await_match(uri, "bob", "another real password"),
            )
            assert {color_a, color_b} == {"white", "black"}

            # Alice disconnects mid-match - a real close, not a mock.
            await client_a.close()

            # Bob (still connected) receives the real countdown message
            # almost immediately - the game is NOT already over.
            countdown_message = await asyncio.wait_for(client_b.recv(), timeout=_RECV_TIMEOUT_S)
            assert countdown_message == f"opponent_disconnected:{_SHORT_COUNTDOWN_S:g}"

            # Well before the countdown expires, Bob can still play a
            # real move if it's his own turn/color - proving the game
            # itself has not ended just because Alice disconnected.
            if color_b == "white":
                await client_b.send("WPe2e4")
            else:
                await client_b.send("BPe7e5")
            # A real MoveAccepted wire event - NOT a "rejected:game_over"
            # response - proves the match is still genuinely live.
            move_response = await asyncio.wait_for(client_b.recv(), timeout=_RECV_TIMEOUT_S)
            assert move_response.startswith(EVENT_MESSAGE_PREFIX)

            await client_b.close()

    asyncio.run(scenario())


def test_the_countdown_expiring_with_no_reconnect_produces_a_real_gameover_favoring_the_opponent():
    async def scenario():
        async with _running_game_server(disconnect_countdown_s=_SHORT_COUNTDOWN_S) as (uri, _game_server):
            (client_a, color_a, _rating_a, _board_a), (client_b, color_b, _rating_b, _board_b) = await asyncio.gather(
                _join_and_await_match(uri, "alice", "correct horse battery staple"),
                _join_and_await_match(uri, "bob", "another real password"),
            )

            await client_a.close()

            countdown_message = await asyncio.wait_for(client_b.recv(), timeout=_RECV_TIMEOUT_S)
            assert countdown_message.startswith("opponent_disconnected:")

            # Real wait past the (short, overridden) countdown - no
            # reconnect ever happens for Alice.
            gameover_wire = await asyncio.wait_for(client_b.recv(), timeout=_RECV_TIMEOUT_S)
            assert gameover_wire.startswith(EVENT_MESSAGE_PREFIX)
            event = parse_game_event(gameover_wire)
            assert event.winner_color.name.lower() == color_b

            await client_b.close()

    asyncio.run(scenario())


def test_the_same_username_reconnecting_within_the_countdown_resumes_the_same_match_and_cancels_the_countdown():
    async def scenario():
        async with _running_game_server(disconnect_countdown_s=_RECONNECT_COUNTDOWN_S) as (uri, _game_server):
            (client_a, color_a, rating_a, board_a), (client_b, color_b, _rating_b, _board_b) = await asyncio.gather(
                _join_and_await_match(uri, "alice", "correct horse battery staple"),
                _join_and_await_match(uri, "bob", "another real password"),
            )

            await client_a.close()

            countdown_message = await asyncio.wait_for(client_b.recv(), timeout=_RECV_TIMEOUT_S)
            assert countdown_message.startswith("opponent_disconnected:")

            # Alice reconnects with the SAME username/password, well
            # before the short countdown expires - a real, brand new
            # connection object; the OLD one is gone forever.
            new_client_a = await websockets.connect(uri)
            await new_client_a.send(format_auth_command("alice", "correct horse battery staple"))
            # No searching_for_opponent this time - resuming a pending
            # disconnect skips matchmaking entirely.
            welcome_a2 = await asyncio.wait_for(new_client_a.recv(), timeout=_RECV_TIMEOUT_S)
            color_a2, rating_a2 = _parse_assigned_color_and_rating(welcome_a2)
            board_a2 = await asyncio.wait_for(new_client_a.recv(), timeout=_RECV_TIMEOUT_S)

            # Exact same color, exact same rating, exact same board -
            # the SAME GameSession, resumed, not a fresh match.
            assert color_a2 == color_a
            assert rating_a2 == rating_a
            assert board_a2 == board_a

            # Bob is told the disconnection was resolved.
            resolved_message = await asyncio.wait_for(client_b.recv(), timeout=_RECV_TIMEOUT_S)
            assert resolved_message == "opponent_reconnected"

            # The countdown must be genuinely cancelled - waiting past
            # what would have been its own expiry produces no GameOver.
            await asyncio.sleep(_RECONNECT_COUNTDOWN_S + _REACTION_DELAY_S)

            # A further real move still works correctly, broadcast to
            # BOTH the resumed connection and Bob.
            if color_a2 == "white":
                await new_client_a.send("WPe2e4")
            else:
                await new_client_a.send("BPe7e5")

            move_wire_a = await asyncio.wait_for(new_client_a.recv(), timeout=_RECV_TIMEOUT_S)
            move_wire_b = await asyncio.wait_for(client_b.recv(), timeout=_RECV_TIMEOUT_S)
            assert move_wire_a.startswith(EVENT_MESSAGE_PREFIX)
            assert move_wire_a == move_wire_b
            assert "MOVE" in move_wire_a

            await new_client_a.close()
            await client_b.close()

    asyncio.run(scenario())


def test_a_disconnect_while_merely_waiting_in_the_matchmaking_queue_is_completely_unaffected():
    async def scenario():
        async with _running_game_server(disconnect_countdown_s=_SHORT_COUNTDOWN_S) as (uri, game_server):
            client = await websockets.connect(uri)
            await client.send(format_auth_command("vanisher", "a real password"))
            searching = await asyncio.wait_for(client.recv(), timeout=_RECV_TIMEOUT_S)
            assert searching == SEARCHING_FOR_OPPONENT_MESSAGE

            # Disconnect WHILE still queued (never matched) - this
            # stage's own explicit requirement 1: the pre-existing
            # matchmaking-queue disconnect path must stay completely
            # untouched by the new active-match disconnect logic.
            await client.close()
            await asyncio.sleep(_REACTION_DELAY_S)

            assert game_server._matchmaking_queue.find_match() is None
            # No disconnect-countdown state was ever created for this
            # username - this scenario never reached an ACTIVE match at
            # all, so this stage's own new tracking must never engage.
            assert game_server._pending_disconnects == {}

            # The server itself is still healthy - a real, subsequent
            # lone client still times out normally via the PRE-EXISTING
            # matchmaking-timeout mechanism, untouched.
            async with websockets.connect(uri) as client2:
                await client2.send(format_auth_command("still_alive", "a real password"))
                await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)  # searching

    asyncio.run(scenario())
