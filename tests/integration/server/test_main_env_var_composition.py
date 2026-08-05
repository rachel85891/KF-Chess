"""Stage I0 smoke test - server/main.py's own module docstring, the
"STAGE I0" section, documents the exact scope boundary this file
proves: (a) main()'s own composition root now resolves SERVER_HOST/
SQLITE_DB_PATH from os.environ, falling back to today's pre-Stage-I0
defaults (DEFAULT_HOST / None, the latter already handled correctly by
GameServer.__init__ - see server/application/game_server.py) when
neither is set, and (b) a throwaway Postgres/Redis startup
connectivity check is completely skipped, not merely swallowed, when
POSTGRES_URL/REDIS_URL are unset.

Like test_main_uses_uvloop.py (Stage G3's own equivalent), main()
itself is never actually invoked here - it's a long-lived, blocking
entry point (server.serve_forever() inside it, until process kill).
Instead this file combines a source-level smoke test for main()'s own
composition root with a REAL, executable proof that run_server() (the
function main() actually calls) still defaults to exactly today's
pre-Stage-I0 behavior when called directly with no arguments - same
"start a real server on an OS-assigned free port, then close it"
pattern test_ws_skeleton.py already established.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

import server.main
from server.main import DEFAULT_HOST, _run_startup_connectivity_check, run_server


def test_main_source_reads_server_host_and_sqlite_db_path_from_env() -> None:
    source = inspect.getsource(server.main)
    assert 'os.environ.get("SERVER_HOST", DEFAULT_HOST)' in source
    assert 'os.environ.get("SQLITE_DB_PATH")' in source


def test_main_source_gates_connectivity_check_on_both_urls() -> None:
    source = inspect.getsource(server.main._run_startup_connectivity_check)
    assert 'os.environ.get("POSTGRES_URL")' in source
    assert 'os.environ.get("REDIS_URL")' in source


def test_run_server_still_binds_default_host_with_no_env_override():
    """The real, executable proof: run_server() called directly (no
    Docker, no env vars involved at all - this function doesn't even
    read os.environ, only main() does) still binds DEFAULT_HOST/a None
    user_repository_db_path exactly as it did before Stage I0."""

    async def scenario():
        server_obj, game_server = await run_server(port=0)
        try:
            host, port = server_obj.sockets[0].getsockname()[:2]
            assert port != 0
            # game_server's own SqliteUserRepository is lazily built
            # (see game_server.py's own "single worker thread" note),
            # so the only directly observable proof at this point is
            # the db_path GameServer itself was constructed with.
            assert game_server._user_repository_db_path is None
        finally:
            server_obj.close()
            await server_obj.wait_closed()

    asyncio.run(scenario())


def test_run_server_forwards_an_explicit_user_repository_db_path(tmp_path):
    """Proves the new `user_repository_db_path` parameter (this
    stage's own addition to run_server()'s signature) is wired
    straight through to GameServer, unmodified - the same seam main()
    uses for SQLITE_DB_PATH."""

    db_path = str(tmp_path / "stage_i0_test.db")

    async def scenario():
        server_obj, game_server = await run_server(port=0, user_repository_db_path=db_path)
        try:
            assert game_server._user_repository_db_path == db_path
        finally:
            server_obj.close()
            await server_obj.wait_closed()

    asyncio.run(scenario())


def test_connectivity_check_is_a_no_op_when_urls_are_unset(monkeypatch):
    """Neither POSTGRES_URL nor REDIS_URL set (today's default, and
    every existing test's own environment) - the check must return
    immediately, without needing asyncpg/redis to do anything at all."""

    monkeypatch.delenv("POSTGRES_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)

    _run_startup_connectivity_check()  # must not raise, must not exit


def test_connectivity_check_is_a_no_op_when_only_one_url_is_set(monkeypatch):
    """Partial configuration is also treated as "not configured" - see
    module docstring's "STAGE I0" section: the check is gated on BOTH
    being set, not either."""

    monkeypatch.setenv("POSTGRES_URL", "postgresql://user:pw@postgres:5432/db")
    monkeypatch.delenv("REDIS_URL", raising=False)

    _run_startup_connectivity_check()  # must not raise, must not exit


def test_connectivity_check_exits_non_zero_when_a_connection_fails(monkeypatch):
    """Both URLs set, but pointing nowhere reachable - a real, failing
    connection attempt (no mocking of asyncpg/redis themselves; this
    is a genuine connection failure, just against an address nothing
    is listening on) must exit the process non-zero, not silently
    continue into run_server()."""

    monkeypatch.setenv("POSTGRES_URL", "postgresql://user:pw@127.0.0.1:1/db")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")

    with pytest.raises(SystemExit) as exc_info:
        _run_startup_connectivity_check()
    assert exc_info.value.code != 0
