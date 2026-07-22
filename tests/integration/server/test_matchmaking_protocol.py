"""Real, end-to-end integration tests for Stage E1's matchmaking queue
wired into GameServer (server/application/game_server.py's own new
"STAGE E1 - REAL MATCHMAKING..." docstring section) - a REAL server
(real GameServer, real MatchmakingQueue, real background tick loop) and
REAL websockets clients, mirroring this project's own established "real
server, real client, no mocking" convention.

WHY BOTH CLIENTS' OWN AUTH+WAIT SEQUENCES ARE RUN CONCURRENTLY (via
asyncio.gather), NEVER ONE FULLY BEFORE THE OTHER - a REAL, STRUCTURAL
CONSEQUENCE OF REAL MATCHMAKING, NOT A TEST-STYLE PREFERENCE: under the
OLD fixed-single-game model, `client1.recv()` (awaiting assigned_color)
returned near-instantly, so tests could freely do
"send1, recv1, send2, recv2" in strict sequence. Under REAL
matchmaking, a client's own assigned_color response does not arrive
until a COMPATIBLE OPPONENT has also joined the queue - if a test
awaited client1's own response BEFORE client2 had even sent its own
AUTH command, it would hang forever (client2 can never arrive in time
to complete a match neither test statement has reached yet). Every
scenario below therefore issues BOTH clients' own "connect, auth, wait
for the outcome" sequences as concurrent coroutines from the very
start (asyncio.gather), exactly mirroring how two REAL, independent
human players would actually connect - at genuinely overlapping times,
never one strictly after the other finishes joining.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
import websockets
from websockets.exceptions import ConnectionClosed

from kungfu_chess.notation.auth_command_format import format_auth_command
from server.application.game_server import GameServer
from server.persistence.user_repository import DEFAULT_STARTING_RATING, UserRepository
from server.presentation.protocol_handler import SEARCHING_FOR_OPPONENT_MESSAGE

_RECV_TIMEOUT_S = 20.0
_SHORT_TIMEOUT_S = 1.0


@asynccontextmanager
async def _running_game_server(user_repository_db_path: str, matchmaking_timeout_s: float = 60.0):
    game_server = GameServer(user_repository_db_path=user_repository_db_path, matchmaking_timeout_s=matchmaking_timeout_s)
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
        server.close()
        await server.wait_closed()


def _parse_assigned_color_and_rating(message: str) -> tuple[str, int]:
    _, color_name, rating_text = message.split(":", 2)
    return color_name, int(rating_text)


async def _join_and_await_outcome(uri: str, username: str, password: str):
    """Connect, authenticate, drain the (always-sent) searching-for-
    opponent message, and return (connection, final_first_stage_message)
    - the final message is either "assigned_color:..." or
    "matchmaking_timeout:...". The connection is returned, still open,
    so the caller can keep using it (e.g. to play a real move, or to
    drain the board-state message that follows a real match)."""

    client = await websockets.connect(uri)
    await client.send(format_auth_command(username, password))
    searching = await asyncio.wait_for(client.recv(), timeout=_RECV_TIMEOUT_S)
    assert searching == SEARCHING_FOR_OPPONENT_MESSAGE
    outcome = await asyncio.wait_for(client.recv(), timeout=_RECV_TIMEOUT_S)
    return client, outcome


def test_two_close_rating_clients_get_matched_and_a_real_move_broadcasts_correctly_to_just_the_pair(tmp_path):
    async def scenario():
        async with _running_game_server(":memory:") as (uri, _game_server):
            (client1, outcome1), (client2, outcome2) = await asyncio.gather(
                _join_and_await_outcome(uri, "alice", "correct horse battery staple"),
                _join_and_await_outcome(uri, "bob", "another real password"),
            )
            try:
                color1, rating1 = _parse_assigned_color_and_rating(outcome1)
                color2, rating2 = _parse_assigned_color_and_rating(outcome2)

                # Both are brand-new accounts - same default rating,
                # always within range - and opposite colors.
                assert {color1, color2} == {"white", "black"}
                assert rating1 == DEFAULT_STARTING_RATING
                assert rating2 == DEFAULT_STARTING_RATING

                board1 = await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)
                board2 = await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)
                assert board1 == board2  # both see the identical, real starting position

                white_client, black_client = (client1, client2) if color1 == "white" else (client2, client1)

                # A real move, from the real White client - proves the
                # match's own GameSession is genuinely wired up and its
                # own tick loop genuinely advances real time.
                await white_client.send("WPe2e4")

                # MoveAccepted (wire event + board text + state
                # snapshot) fires immediately for BOTH clients - drained
                # here, not asserted on (mirrors this project's own
                # established drain-then-assert-on-arrival convention).
                for _ in range(3):
                    await asyncio.wait_for(white_client.recv(), timeout=_RECV_TIMEOUT_S)
                    await asyncio.wait_for(black_client.recv(), timeout=_RECV_TIMEOUT_S)

                # PieceArrived's own wire event, then its own final
                # board text, once the tick loop's real elapsed time
                # completes the 2-square motion.
                await asyncio.wait_for(white_client.recv(), timeout=_RECV_TIMEOUT_S)  # wire event
                await asyncio.wait_for(black_client.recv(), timeout=_RECV_TIMEOUT_S)
                board_after_1 = await asyncio.wait_for(white_client.recv(), timeout=_RECV_TIMEOUT_S)
                board_after_2 = await asyncio.wait_for(black_client.recv(), timeout=_RECV_TIMEOUT_S)

                assert board_after_1 == board_after_2
                lines = board_after_1.splitlines()
                assert lines[6].split()[4] == "."  # e2 now empty
                assert lines[4].split()[4] == "wP"  # e4 now holds the white pawn
            finally:
                await client1.close()
                await client2.close()

    asyncio.run(scenario())


def test_two_far_rating_clients_do_not_match_each_other_and_both_time_out(tmp_path):
    async def scenario():
        # A real, pre-seeded high-rated account, via a real FILE (not
        # ":memory:") - shared, through the filesystem, with GameServer's
        # own separately/lazily-constructed UserRepository (see
        # server/application/game_server.py's own "LAZY, THREAD-PINNED
        # CONSTRUCTION" docstring section for why a shared connection
        # OBJECT could never be used here instead).
        db_path = str(tmp_path / "matchmaking_far_ratings_test.db")
        seed_repo = UserRepository(db_path=db_path)
        seed_repo.create_account("grandmaster", "correct horse battery staple")
        seed_repo.update_rating("grandmaster", 2000)  # 800 points from a fresh 1200 account

        async with _running_game_server(db_path, matchmaking_timeout_s=_SHORT_TIMEOUT_S) as (uri, _game_server):
            (client1, outcome1), (client2, outcome2) = await asyncio.gather(
                _join_and_await_outcome(uri, "grandmaster", "correct horse battery staple"),
                _join_and_await_outcome(uri, "newbie", "a real password"),
            )
            try:
                assert outcome1.startswith("matchmaking_timeout:")
                assert outcome2.startswith("matchmaking_timeout:")

                # Both connections are then closed server-side.
                with pytest.raises(ConnectionClosed):
                    await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)
                with pytest.raises(ConnectionClosed):
                    await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)
            finally:
                await client1.close()
                await client2.close()

    asyncio.run(scenario())


def test_a_lone_client_with_no_compatible_opponent_times_out_with_the_correct_message():
    async def scenario():
        async with _running_game_server(":memory:", matchmaking_timeout_s=_SHORT_TIMEOUT_S) as (uri, _game_server):
            async with websockets.connect(uri) as client:
                await client.send(format_auth_command("solo", "a real password"))
                searching = await asyncio.wait_for(client.recv(), timeout=_RECV_TIMEOUT_S)
                assert searching == SEARCHING_FOR_OPPONENT_MESSAGE

                timeout_message = await asyncio.wait_for(client.recv(), timeout=_RECV_TIMEOUT_S)
                assert timeout_message.startswith("matchmaking_timeout:")
                assert f"{_SHORT_TIMEOUT_S:g}" in timeout_message

                with pytest.raises(ConnectionClosed):
                    await asyncio.wait_for(client.recv(), timeout=_RECV_TIMEOUT_S)

    asyncio.run(scenario())


def test_disconnecting_while_still_waiting_in_queue_leaves_no_stale_entry_behind():
    async def scenario():
        async with _running_game_server(":memory:", matchmaking_timeout_s=_SHORT_TIMEOUT_S) as (uri, game_server):
            client = await websockets.connect(uri)
            await client.send(format_auth_command("vanisher", "a real password"))
            searching = await asyncio.wait_for(client.recv(), timeout=_RECV_TIMEOUT_S)
            assert searching == SEARCHING_FOR_OPPONENT_MESSAGE

            # Disconnect WHILE still queued (never matched, never timed
            # out yet) - the real bug class Part B's own requirement 5
            # guards against.
            await client.close()

            # Give the server's own handle_connection coroutine a real
            # moment to react to the disconnect.
            await asyncio.sleep(0.2)

            assert game_server._matchmaking_queue.find_match() is None
            # A real, subsequent lone client still times out normally -
            # proving the server itself is healthy and the vanished
            # entry did not corrupt the queue.
            async with websockets.connect(uri) as client2:
                await client2.send(format_auth_command("still_alive", "a real password"))
                await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)  # searching
                timeout_message = await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)
                assert timeout_message.startswith("matchmaking_timeout:")

    asyncio.run(scenario())
