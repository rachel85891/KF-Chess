"""Real, end-to-end integration tests for Stage D2's real username+
password authentication protocol (server/application/game_server.py's
own new pre-assigned_color AUTH handshake, backed by
server/persistence/user_repository.py's UserRepository) - a REAL server
(real GameServer, real UserRepository backed by an in-memory SQLite
database so this test file never touches disk) and REAL websockets
clients, mirroring this project's own established "real server, real
client, no mocking" convention
(tests/integration/server/test_protocol_wiring.py's own identical
helper shape).

WHY ONE SHARED UserRepository INSTANCE PER SCENARIO, NOT A FRESH ONE
PER CONNECTION: mirrors GameServer's own real production wiring (ONE
UserRepository constructed for the server's whole lifetime, per this
stage's own "Part A" requirement) - a fresh UserRepository per
connection would defeat the entire point of persistence (a second
connection using the same username would see a brand-new, empty users
table instead of the first connection's already-created account).
":memory:" is safe to share here specifically because it is the SAME
UserRepository object/connection throughout one test's whole scenario,
never reopened - the same real semantics UserRepository's own test
suite already relies on for its own ":memory:"-backed tests.
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

_RECV_TIMEOUT_S = 5.0


@asynccontextmanager
async def _running_game_server(user_repository: UserRepository):
    game_server = GameServer(user_repository=user_repository)
    server = await websockets.serve(game_server.handle_connection, "localhost", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        yield f"ws://localhost:{port}", game_server
    finally:
        server.close()
        await server.wait_closed()


def _parse_assigned_color_and_rating(message: str) -> tuple[str, int]:
    """"assigned_color:white:1200" -> ("white", 1200)."""

    _, color_name, rating_text = message.split(":", 2)
    return color_name, int(rating_text)


def test_a_new_username_creates_an_account_with_the_default_starting_rating():
    async def scenario():
        repo = UserRepository(db_path=":memory:")
        async with _running_game_server(repo) as (uri, _game_server):
            async with websockets.connect(uri) as client:
                await client.send(format_auth_command("alice", "correct horse battery staple"))
                welcome = await asyncio.wait_for(client.recv(), timeout=_RECV_TIMEOUT_S)

        color_name, rating = _parse_assigned_color_and_rating(welcome)
        assert color_name == "white"
        assert rating == DEFAULT_STARTING_RATING
        # The real account now exists, with the password just used.
        assert repo.verify_login("alice", "correct horse battery staple") is True

    asyncio.run(scenario())


def test_existing_username_with_correct_password_logs_in_and_returns_the_real_stored_rating():
    async def scenario():
        repo = UserRepository(db_path=":memory:")
        repo.create_account("alice", "correct horse battery staple")
        repo.update_rating("alice", 1450)  # a distinguishable, non-default rating

        async with _running_game_server(repo) as (uri, _game_server):
            async with websockets.connect(uri) as client:
                await client.send(format_auth_command("alice", "correct horse battery staple"))
                welcome = await asyncio.wait_for(client.recv(), timeout=_RECV_TIMEOUT_S)

        color_name, rating = _parse_assigned_color_and_rating(welcome)
        assert color_name == "white"
        assert rating == 1450  # the REAL stored rating, not the default

    asyncio.run(scenario())


def test_existing_username_with_wrong_password_is_rejected_and_the_connection_closes_with_no_session_state_created():
    async def scenario():
        repo = UserRepository(db_path=":memory:")
        repo.create_account("alice", "correct horse battery staple")

        async with _running_game_server(repo) as (uri, game_server):
            async with websockets.connect(uri) as client:
                await client.send(format_auth_command("alice", "totally wrong password"))
                rejection = await asyncio.wait_for(client.recv(), timeout=_RECV_TIMEOUT_S)

                assert rejection == "rejected:wrong_password"
                with pytest.raises(ConnectionClosed):
                    await asyncio.wait_for(client.recv(), timeout=_RECV_TIMEOUT_S)

            # Never tracked as a connection at all - the exact same
            # "no partial/viewer capacity granted" guarantee
            # server_full's own rejection path already established
            # (server/application/game_server.py's own "THIRD-PLUS
            # CONNECTION POLICY" docstring section), now proven for a
            # rejected LOGIN attempt too.
            assert game_server._connection_manager.connection_count == 0
            assert len(game_server._colors) == 0

    asyncio.run(scenario())


def test_a_malformed_auth_command_is_rejected_and_does_not_crash_the_server_which_keeps_accepting_valid_connections():
    async def scenario():
        repo = UserRepository(db_path=":memory:")

        async with _running_game_server(repo) as (uri, _game_server):
            async with websockets.connect(uri) as bad_client:
                await bad_client.send("not a real auth command")
                rejection = await asyncio.wait_for(bad_client.recv(), timeout=_RECV_TIMEOUT_S)
                assert "rejected" in rejection
                with pytest.raises(ConnectionClosed):
                    await asyncio.wait_for(bad_client.recv(), timeout=_RECV_TIMEOUT_S)

            # The server process itself must still be healthy
            # afterward - proven by a real, subsequent valid login
            # still working normally.
            async with websockets.connect(uri) as good_client:
                await good_client.send(format_auth_command("bob", "a real password"))
                welcome = await asyncio.wait_for(good_client.recv(), timeout=_RECV_TIMEOUT_S)
                color_name, rating = _parse_assigned_color_and_rating(welcome)
                assert color_name == "white"
                assert rating == DEFAULT_STARTING_RATING

    asyncio.run(scenario())
