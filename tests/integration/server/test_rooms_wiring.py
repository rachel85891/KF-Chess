"""Real, end-to-end integration tests for Stage F4's room wiring
(server/application/game_server.py's own "STAGE F4" docstring section)
- a REAL server (real GameServer, real SessionCoordinator, real
background tick loop) and REAL websockets clients, mirroring
test_matchmaking_protocol.py's own "real server, real client, no
mocking, concurrent asyncio.gather joins" convention exactly.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
import websockets
from websockets.exceptions import ConnectionClosed

from kungfu_chess.notation.auth_command_format import format_auth_command
from server.application.game_server import GameServer

# Marked slow: this file constructs a real, background-threaded/tasked
# server and relies on real wall-clock waiting (asyncio.sleep/time.sleep,
# real tick-loop cadence, or real network round trips) - excluded from
# `pytest -m "not slow"` for fast, deterministic day-to-day runs; still
# run in full via the dedicated slow/real-time pass.
pytestmark = pytest.mark.slow

_RECV_TIMEOUT_S = 20.0
_REACTION_DELAY_S = 0.3  # a real moment for the server's own coroutine to react


@asynccontextmanager
async def _running_game_server(start_tick_loop: bool = True):
    game_server = GameServer(user_repository_db_path=":memory:")
    server = await websockets.serve(game_server.handle_connection, "localhost", 0)
    tick_task = asyncio.create_task(game_server.run_tick_loop()) if start_tick_loop else None
    try:
        port = server.sockets[0].getsockname()[1]
        yield f"ws://localhost:{port}", game_server
    finally:
        if tick_task is not None:
            tick_task.cancel()
            try:
                await tick_task
            except asyncio.CancelledError:
                pass
        # A brief, real moment for every just-disconnected connection's
        # own handle_connection coroutine to actually reach
        # _handle_active_match_disconnect and register its own pending
        # countdown (a genuine scheduling race when clients close
        # back-to-back - see server/application/game_server.py's own
        # "STAGE - SERVER SHUTDOWN..." docstring section) before
        # shutdown() resolves whatever is currently pending.
        await asyncio.sleep(0.2)
        await game_server.shutdown()
        server.close()
        await server.wait_closed()


def _parse_assigned_color_and_rating(message: str) -> tuple[str, int]:
    _, color_name, rating_text = message.split(":", 2)
    return color_name, int(rating_text)


def test_host_creates_room_guest_joins_both_get_matched_and_a_real_move_broadcasts_to_both():
    async def scenario():
        async with _running_game_server() as (uri, _game_server):
            host = await websockets.connect(uri)
            await host.send(format_auth_command("alice", "correct horse battery staple"))
            await host.send("CREATE_ROOM")
            room_created = await asyncio.wait_for(host.recv(), timeout=_RECV_TIMEOUT_S)
            assert room_created.startswith("room_created:")
            code = room_created.split(":", 1)[1]

            guest = await websockets.connect(uri)
            await guest.send(format_auth_command("bob", "another real password"))
            await guest.send(f"JOIN_ROOM:{code}")

            room_joined = await asyncio.wait_for(guest.recv(), timeout=_RECV_TIMEOUT_S)
            assert room_joined == "room_joined:guest"

            host_welcome = await asyncio.wait_for(host.recv(), timeout=_RECV_TIMEOUT_S)
            guest_welcome = await asyncio.wait_for(guest.recv(), timeout=_RECV_TIMEOUT_S)
            host_color, _host_rating = _parse_assigned_color_and_rating(host_welcome)
            guest_color, _guest_rating = _parse_assigned_color_and_rating(guest_welcome)

            # Host=White, Guest=Black - see module docstring's "STAGE F4"
            # section for the full reasoning.
            assert host_color == "white"
            assert guest_color == "black"

            host_board = await asyncio.wait_for(host.recv(), timeout=_RECV_TIMEOUT_S)
            guest_board = await asyncio.wait_for(guest.recv(), timeout=_RECV_TIMEOUT_S)
            assert host_board == guest_board

            # A real move, from the real White (host) client - proves a
            # genuine, live GameSession backs this room-based match.
            await host.send("WPe2e4")

            for _ in range(3):
                await asyncio.wait_for(host.recv(), timeout=_RECV_TIMEOUT_S)
                await asyncio.wait_for(guest.recv(), timeout=_RECV_TIMEOUT_S)
            await asyncio.wait_for(host.recv(), timeout=_RECV_TIMEOUT_S)  # PieceArrived wire event
            await asyncio.wait_for(guest.recv(), timeout=_RECV_TIMEOUT_S)
            board_after_host = await asyncio.wait_for(host.recv(), timeout=_RECV_TIMEOUT_S)
            board_after_guest = await asyncio.wait_for(guest.recv(), timeout=_RECV_TIMEOUT_S)

            assert board_after_host == board_after_guest
            lines = board_after_host.splitlines()
            assert lines[6].split()[4] == "."  # e2 now empty
            assert lines[4].split()[4] == "wP"  # e4 now holds the white pawn

            await host.close()
            await guest.close()

    asyncio.run(scenario())


def test_join_room_with_a_code_that_was_never_created_receives_room_not_found_and_closes():
    async def scenario():
        async with _running_game_server() as (uri, _game_server):
            client = await websockets.connect(uri)
            await client.send(format_auth_command("alice", "correct horse battery staple"))
            await client.send("JOIN_ROOM:NOPE00")

            reply = await asyncio.wait_for(client.recv(), timeout=_RECV_TIMEOUT_S)
            assert reply == "room_not_found"

            with pytest.raises(ConnectionClosed):
                await asyncio.wait_for(client.recv(), timeout=_RECV_TIMEOUT_S)

    asyncio.run(scenario())


def test_a_third_client_joining_a_full_room_becomes_a_viewer_and_then_closes():
    async def scenario():
        async with _running_game_server() as (uri, _game_server):
            host = await websockets.connect(uri)
            await host.send(format_auth_command("alice", "correct horse battery staple"))
            await host.send("CREATE_ROOM")
            room_created = await asyncio.wait_for(host.recv(), timeout=_RECV_TIMEOUT_S)
            code = room_created.split(":", 1)[1]

            guest = await websockets.connect(uri)
            await guest.send(format_auth_command("bob", "another real password"))
            await guest.send(f"JOIN_ROOM:{code}")
            assert await asyncio.wait_for(guest.recv(), timeout=_RECV_TIMEOUT_S) == "room_joined:guest"

            # Drain host/guest's own assigned_color+board messages so
            # they don't interfere with this test's own viewer-only
            # assertions.
            await asyncio.wait_for(host.recv(), timeout=_RECV_TIMEOUT_S)
            await asyncio.wait_for(host.recv(), timeout=_RECV_TIMEOUT_S)
            await asyncio.wait_for(guest.recv(), timeout=_RECV_TIMEOUT_S)
            await asyncio.wait_for(guest.recv(), timeout=_RECV_TIMEOUT_S)

            viewer = await websockets.connect(uri)
            await viewer.send(format_auth_command("carol", "yet another password"))
            await viewer.send(f"JOIN_ROOM:{code}")

            reply = await asyncio.wait_for(viewer.recv(), timeout=_RECV_TIMEOUT_S)
            assert reply == "room_joined:viewer"

            # No further board/event message ever arrives for this
            # connection - it is closed immediately (see module
            # docstring's own "ACCEPTED SCOPE BOUNDARY" section).
            with pytest.raises(ConnectionClosed):
                await asyncio.wait_for(viewer.recv(), timeout=_RECV_TIMEOUT_S)

            await host.close()
            await guest.close()

    asyncio.run(scenario())


def test_host_disconnects_before_any_guest_joins_then_a_later_join_attempt_gets_room_not_found():
    async def scenario():
        async with _running_game_server() as (uri, _game_server):
            host = await websockets.connect(uri)
            await host.send(format_auth_command("alice", "correct horse battery staple"))
            await host.send("CREATE_ROOM")
            room_created = await asyncio.wait_for(host.recv(), timeout=_RECV_TIMEOUT_S)
            code = room_created.split(":", 1)[1]

            # The host disconnects before anyone ever joins - the server
            # must not hang.
            await host.close()
            await asyncio.sleep(_REACTION_DELAY_S)

            guest = await websockets.connect(uri)
            await guest.send(format_auth_command("bob", "another real password"))
            await guest.send(f"JOIN_ROOM:{code}")

            reply = await asyncio.wait_for(guest.recv(), timeout=_RECV_TIMEOUT_S)
            assert reply == "room_not_found"

            with pytest.raises(ConnectionClosed):
                await asyncio.wait_for(guest.recv(), timeout=_RECV_TIMEOUT_S)

    asyncio.run(scenario())


def test_play_still_matchmakes_two_play_clients_exactly_as_before_non_regression():
    async def scenario():
        async with _running_game_server() as (uri, _game_server):
            client1 = await websockets.connect(uri)
            client2 = await websockets.connect(uri)

            await client1.send(format_auth_command("alice", "correct horse battery staple"))
            await client2.send(format_auth_command("bob", "another real password"))

            # The room choice ("PLAY") must be sent BEFORE waiting for
            # searching_for_opponent - the server now reads it first
            # (Stage F4) before ever sending that message.
            await client1.send("PLAY")
            await client2.send("PLAY")

            searching1 = await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)
            searching2 = await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)
            assert searching1 == "searching_for_opponent"
            assert searching2 == "searching_for_opponent"

            welcome1 = await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)
            welcome2 = await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)
            color1, _rating1 = _parse_assigned_color_and_rating(welcome1)
            color2, _rating2 = _parse_assigned_color_and_rating(welcome2)
            assert {color1, color2} == {"white", "black"}

            board1 = await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)
            board2 = await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)
            assert board1 == board2

            await client1.close()
            await client2.close()

    asyncio.run(scenario())
