"""Real, end-to-end integration test for Stage D3's ELO rating update
(server/application/game_server.py's own new "STAGE D3" docstring
section) - a real GameServer-backed server (own background thread +
loop, mirroring test_network_game_loop_runner_gameover.py's own
_BackgroundTestServer/session-injection pattern exactly) and a real
NetworkGameLoopRunner (headless), reusing that same file's own King-
capture-via-real-move scenario shape (simpler than interception, per
this stage's own "king capture is simplest" suggestion) - a real King
capture (1) triggers the real, existing GameOver mechanism unchanged,
(2) causes GameServer to compute and persist a real ELO update for BOTH
players via a real, file-backed UserRepository, and (3) both players'
own real clients receive and display it.

WHY A REAL, FILE-BACKED UserRepository (tmp_path), NOT ":memory:": this
test needs to (a) pre-seed both accounts at KNOWN, DISTINCT ratings
before the server ever starts (an in-memory database is private to the
one connection that creates it - GameServer's own UserRepository is
lazily constructed on its own separate worker thread, so a separately-
constructed ":memory:" UserRepository could never share data with it -
see game_server.py's own "LAZY, THREAD-PINNED CONSTRUCTION" docstring
section, and Stage E1's own test_matchmaking_protocol.py's identical
reasoning for its own far-rating test), and (b) independently re-open
the SAME database AFTER the game ends to verify both ratings were
genuinely persisted, not merely broadcast over the wire.

WHY THE "OPPONENT" SIDE IS A RAW NetworkGameClient, NOT A SECOND
NetworkGameLoopRunner: mirrors test_network_game_loop_runner_opponent_
disconnect.py's own identical precedent - this test only needs to
prove what the REAL NetworkGameLoopRunner under test does with a real
rating_update message; the opponent's own rendering is not under test.

WHICH SIDE ENDS UP WHITE IS GENUINELY RACY (Stage E1 - color assignment
is queue-join order, not username-based) - this test identifies which
username actually became White/Black from the real, observed
assigned_color responses, then computes the EXPECTED new ratings from
THAT observed mapping via the same real elo_rating.compute_new_ratings
this stage's own GameServer code calls, rather than assuming a fixed
mapping.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Optional

import pytest
import websockets

from kungfu_chess.client.loop.network_game_loop_runner import NetworkGameLoopRunner
from kungfu_chess.client.network.network_game_client import NetworkGameClient
from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece, PieceKind
from kungfu_chess.model.position import Position
from server.application.elo_rating import compute_new_ratings
from server.application.game_server import GameServer
from server.application.game_session import GameSession
from server.persistence.user_repository import UserRepository

# Marked slow: this file constructs a real, background-threaded/tasked
# server and relies on real wall-clock waiting (asyncio.sleep/time.sleep,
# real tick-loop cadence, or real network round trips) - excluded from
# `pytest -m "not slow"` for fast, deterministic day-to-day runs; still
# run in full via the dedicated slow/real-time pass.
pytestmark = pytest.mark.slow


_JOIN_TIMEOUT_S = 5.0
_POLL_INTERVAL_S = 0.05

_ALICE_STARTING_RATING = 1200
_BOB_STARTING_RATING = 1280  # 80 points away - within Stage E1's own ±100 matchmaking range


def _empty_grid(rows: int, cols: int) -> list[list[None]]:
    return [[None for _ in range(cols)] for _ in range(rows)]


def _king_capture_ready_session() -> GameSession:
    """A white rook one square away from a black king - the minimum
    setup for a real, immediate, one-square king-capturing move
    (mirrors test_network_game_loop_runner_gameover.py's own
    interception scenario's shape, but via an ORDINARY move/arrival
    king capture instead of a jump interception - "king capture is
    simplest", per this stage's own task wording)."""

    grid = _empty_grid(3, 3)
    mover = Piece(color=Color.WHITE, kind=PieceKind.ROOK, cell=Position(row=0, col=0))
    king = Piece(color=Color.BLACK, kind=PieceKind.KING, cell=Position(row=0, col=1))
    grid[0][0] = mover
    grid[0][1] = king
    return GameSession(board=Board(grid))


class _BackgroundTestServer:
    """Identical in shape to test_network_game_loop_runner_gameover.py's
    own _BackgroundTestServer, extended with a real, file-backed
    user_repository_db_path (see module docstring for why)."""

    def __init__(self, session: GameSession, db_path: str) -> None:
        self.uri: str = ""
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event: Optional[asyncio.Event] = None
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready, session, db_path), daemon=True)
        self._thread.start()
        if not ready.wait(timeout=_JOIN_TIMEOUT_S):
            raise RuntimeError("background test server failed to start in time")

    def _run(self, ready: threading.Event, session: GameSession, db_path: str) -> None:
        asyncio.run(self._serve(ready, session, db_path))

    async def _serve(self, ready: threading.Event, session: GameSession, db_path: str) -> None:
        game_server = GameServer(session_factory=lambda: session, user_repository_db_path=db_path)
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


def _start_opponent(uri: str, username: str, password: str) -> tuple[NetworkGameClient, threading.Thread]:
    """Starts (but does not wait for) a raw NetworkGameClient "opponent"
    connecting on a background thread - must be started BEFORE
    constructing the real NetworkGameLoopRunner under test, since that
    class's own constructor blocks the calling thread until matched."""

    opponent = NetworkGameClient()
    thread = threading.Thread(target=opponent.connect, args=(uri, username, password), daemon=True)
    thread.start()
    return opponent, thread


def _poll_until(runner: NetworkGameLoopRunner, predicate, timeout_s: float) -> None:
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        runner.poll_and_process()
        if predicate(runner):
            return
        time.sleep(_POLL_INTERVAL_S)


def test_a_real_king_capture_computes_and_persists_a_real_elo_update_and_the_client_displays_it(tmp_path):
    db_path = str(tmp_path / "rating_update_test.db")
    seed_repo = UserRepository(db_path=db_path)
    seed_repo.create_account("alice", "correct horse battery staple")
    seed_repo.update_rating("alice", _ALICE_STARTING_RATING)
    seed_repo.create_account("bob", "another real password")
    seed_repo.update_rating("bob", _BOB_STARTING_RATING)

    session = _king_capture_ready_session()
    test_server = _BackgroundTestServer(session, db_path)
    opponent, opponent_thread = _start_opponent(test_server.uri, "bob", "another real password")
    runner = NetworkGameLoopRunner(test_server.uri, username="alice", password="correct horse battery staple", headless=True)
    try:
        opponent_thread.join(timeout=_JOIN_TIMEOUT_S)
        _poll_until(runner, lambda r: r.board is not None, _JOIN_TIMEOUT_S)

        # Which of alice/bob actually became White is queue-join-order-
        # driven (Stage E1), not username-based - identify it from the
        # real, observed assigned_color responses rather than assuming.
        runner_rating_before = _ALICE_STARTING_RATING
        opponent_rating_before = _BOB_STARTING_RATING
        if runner.assigned_color is Color.WHITE:
            winner_rating_before, loser_rating_before = runner_rating_before, opponent_rating_before
        else:
            winner_rating_before, loser_rating_before = opponent_rating_before, runner_rating_before

        expected_winner_new, expected_loser_new = compute_new_ratings(winner_rating_before, loser_rating_before)
        if runner.assigned_color is Color.WHITE:
            runner_expected_old, runner_expected_new = winner_rating_before, expected_winner_new
            opponent_expected_new = expected_loser_new
        else:
            runner_expected_old, runner_expected_new = loser_rating_before, expected_loser_new
            opponent_expected_new = expected_winner_new

        defender_cell = Position(row=0, col=0)
        king_cell = Position(row=0, col=1)

        # Whichever side is White sends the real, king-capturing move.
        if runner.assigned_color is Color.WHITE:
            runner.network_client.send_move(Color.WHITE, PieceKind.ROOK, defender_cell, king_cell)
        else:
            opponent.send_move(Color.WHITE, PieceKind.ROOK, defender_cell, king_cell)

        _poll_until(runner, lambda r: r._game_over, timeout_s=5.0)
        assert runner._game_over is True

        # The real, client-held rating-update state this stage adds -
        # both the raw (old, new) pair and the live self.rating update.
        _poll_until(runner, lambda r: r._rating_update is not None, timeout_s=5.0)
        assert runner._rating_update == (runner_expected_old, runner_expected_new)
        assert runner.rating == runner_expected_new

        # Both players' own ratings were genuinely PERSISTED, not just
        # broadcast - re-opened from a completely separate, fresh
        # UserRepository instance against the same real db file. The
        # runner is always logged in as "alice", the raw opponent
        # always as "bob" (fixed usernames above), so this is unambiguous
        # regardless of which of the two actually ended up White.
        verify_repo = UserRepository(db_path=db_path)
        assert verify_repo.get_rating("alice") == runner_expected_new
        assert verify_repo.get_rating("bob") == opponent_expected_new
    finally:
        runner.close()
        opponent.close()
        test_server.stop()
