"""ConnectionManager: tracks currently-connected WebSocket clients -
and does nothing else (Stage B1, server track).

SRP, and why this matters for a future stage: ConnectionManager has
zero knowledge of what protocol is spoken over a connection it holds -
not today's throwaway echo, and not a future stage's real chess move
commands either. That knowledge belongs entirely to server/main.py's
handler function (see its own module docstring for the documented
"swap point") - a future stage can replace the ENTIRE application
protocol without this file changing by even one line, because this
file never had an opinion about the protocol to begin with.

Holds plain connection handles (real
websockets.asyncio.server.ServerConnection instances - never a mock or
a wrapper of our own) in a set. No chess-specific data is ever attached
to a connection here (no piece/board/player association) - that
pairing, once a future stage actually needs it, belongs to whatever
component introduces it, kept strictly out of this class per its own
single responsibility.
"""

from __future__ import annotations

from typing import Iterable, Set

from websockets.asyncio.server import ServerConnection


class ConnectionManager:
    """Tracks the set of currently-open connections. See module
    docstring for why this class knows nothing else."""

    def __init__(self) -> None:
        """Create a fresh ConnectionManager with no tracked connections
        yet. No global/module-level state (mirrors
        kungfu_chess.bus.EventBus's own Stage A1 decision, for the same
        reason): a future server may need one ConnectionManager per
        room/game, each fully independent."""

        self._connections: Set[ServerConnection] = set()

    def add(self, connection: ServerConnection) -> None:
        """Start tracking a newly-accepted connection.

        Args:
            connection: The real ServerConnection handle websockets
                handed the server for this client.

        Returns:
            None.
        """

        self._connections.add(connection)

    def remove(self, connection: ServerConnection) -> None:
        """Stop tracking `connection`.

        Args:
            connection: The connection to stop tracking.

        Returns:
            None.

        Safe to call even if `connection` was never added, or has
        already been removed - a discard, not a remove(). The caller
        (server/main.py's handle_connection) always calls this
        unconditionally from a `finally` block regardless of WHY a
        connection's lifetime ended (graceful close, abrupt drop, or a
        future handler-level error), so a no-op double-removal must
        never raise - the same "no-op, not an error" convention
        kungfu_chess.bus.EventBus.unsubscribe already established
        (Stage A1) for the identical reason.
        """

        self._connections.discard(connection)

    @property
    def connection_count(self) -> int:
        """The number of currently-tracked connections."""

        return len(self._connections)

    def connections(self) -> Iterable[ServerConnection]:
        """A snapshot of every currently-tracked connection.

        Returns:
            A frozenset snapshot, not the live internal set - a future
            caller iterating this (e.g. a broadcaster) must not corrupt
            ConnectionManager's own internal state, and must not be
            affected by adds/removes that happen while it iterates.
        """

        return frozenset(self._connections)
