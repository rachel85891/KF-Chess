"""Real, end-to-end integration test for the server-shutdown-hangs-on-
a-pending-disconnect-countdown fix (server/application/game_server.py's
own "SERVER SHUTDOWN" docstring section) - reproduces, with a real
server and real clients, the hang discovered during Stage F2's
diagnostic work: GameServer._handle_active_match_disconnect awaits an
unresolved future for up to disconnect_countdown_s real seconds, and
nothing resolves it when the SERVER ITSELF (as opposed to the countdown
expiring, or a reconnect) is what's shutting down - websockets' own
Server.close()/wait_closed() (the exact sequence server/main.py's own
`async with server:` block performs on exit, per
websockets.asyncio.server.Server.__aexit__) wait for every connection
handler task to actually return, so a graceful shutdown blocks for up
to the full countdown window, or hangs forever if no tick loop is
running to ever expire it (the common case - most integration tests,
and every real reconnect-cancels-the-countdown scenario, never start
one).

Mirrors test_disconnect_countdown_autoresign.py's own "real disconnect
via a real client.close(), never a mock" convention, and uses a long
countdown (_LONG_COUNTDOWN_S) specifically so this test cannot
accidentally pass just because the real countdown happened to expire
on its own during the assertion - the whole point is proving shutdown()
resolves it WITHOUT waiting for that.
"""

from __future__ import annotations

import asyncio
import time

import pytest
import websockets

from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece, PieceKind
from kungfu_chess.model.position import Position
from server.application.game_server import GameServer
from server.application.game_session import GameSession

# Marked slow: this file constructs a real, background-threaded/tasked
# server and relies on real wall-clock waiting (asyncio.sleep/time.sleep,
# real tick-loop cadence, or real network round trips) - excluded from
# `pytest -m "not slow"` for fast, deterministic day-to-day runs; still
# run in full via the dedicated slow/real-time pass.
pytestmark = pytest.mark.slow

_RECV_TIMEOUT_S = 20.0
_LONG_COUNTDOWN_S = 30.0


def _empty_grid(rows: int, cols: int) -> list[list[None]]:
    return [[None for _ in range(cols)] for _ in range(rows)]


def _single_piece_session() -> GameSession:
    """A minimal real GameSession - its own game_over flag is this
    test's own proof that shutdown() never triggers a resign()/GameOver
    side effect (see module docstring)."""

    grid = _empty_grid(3, 3)
    grid[0][0] = Piece(color=Color.WHITE, kind=PieceKind.ROOK, cell=Position(row=0, col=0))
    return GameSession(board=Board(grid))


async def _auth_and_drain(client, username: str, password: str) -> None:
    await client.send(f"AUTH:{username}:{password}")
    # Stage F4 - a real client now chooses a mode after AUTH; "PLAY"
    # reproduces this file's own pre-F4 behavior (unconditional
    # matchmaking) exactly.
    await client.send("PLAY")
    await asyncio.wait_for(client.recv(), timeout=_RECV_TIMEOUT_S)  # searching_for_opponent
    await asyncio.wait_for(client.recv(), timeout=_RECV_TIMEOUT_S)  # assigned_color
    await asyncio.wait_for(client.recv(), timeout=_RECV_TIMEOUT_S)  # board state


def test_shutdown_resolves_pending_disconnect_countdowns_so_close_returns_quickly():
    async def scenario():
        session = _single_piece_session()
        game_server = GameServer(
            session_factory=lambda: session,
            user_repository_db_path=":memory:",
            disconnect_countdown_s=_LONG_COUNTDOWN_S,
        )
        server = await websockets.serve(game_server.handle_connection, "localhost", 0)
        port = server.sockets[0].getsockname()[1]
        uri = f"ws://localhost:{port}"

        # No tick loop is started at all - the common case for most
        # integration tests, and the case that makes the pre-fix bug an
        # INDEFINITE hang rather than a bounded 30s wait (nothing would
        # ever call _check_disconnect_countdowns to expire it).
        async with websockets.connect(uri) as client1, websockets.connect(uri) as client2:
            await asyncio.gather(
                _auth_and_drain(client1, "alice", "password1"),
                _auth_and_drain(client2, "bob", "password2"),
            )
        # Both clients are now closed (the `async with` block above
        # already performed a real graceful close) - give the server's
        # own handler coroutines a real moment to observe
        # ConnectionClosed and register their pending disconnects.
        await asyncio.sleep(0.3)
        assert len(game_server._pending_disconnects) == 2

        t0 = time.perf_counter()
        await game_server.shutdown()
        server.close()
        await asyncio.wait_for(server.wait_closed(), timeout=5.0)
        elapsed = time.perf_counter() - t0

        # Near-instant, not "waited out (a fraction of) the 30s countdown".
        assert elapsed < 1.0
        assert game_server._pending_disconnects == {}
        # _handle_active_match_disconnect's own existing post-resolution
        # cleanup still ran correctly: both connections popped from
        # match.colors, and the now-empty match removed entirely.
        assert game_server._matches == {}
        # No resign()/GameOver was triggered by shutting down - see
        # GameServer.shutdown's own docstring for why this is a plain
        # resolution, not an auto-resign.
        assert session.engine.state.game_over is False

    asyncio.run(scenario())


def test_shutdown_is_a_safe_no_op_with_no_pending_disconnects():
    async def scenario():
        game_server = GameServer(user_repository_db_path=":memory:")

        await game_server.shutdown()  # must not raise

        assert game_server._pending_disconnects == {}

    asyncio.run(scenario())
