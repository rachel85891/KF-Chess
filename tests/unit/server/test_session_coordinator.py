"""Unit tests for Stage F2's InMemorySessionCoordinator (server/
application/session_coordinator.py) that are genuinely specific to THIS
implementation, not the shared SessionCoordinator Protocol contract.

STAGE I2 SPLIT: this file originally held 11 tests; 10 of them only
ever exercised the 3 public Protocol methods and have moved, unmodified
in behavior, to tests/unit/server/test_session_coordinator_contract.py
- a shared, parameterized suite now run against BOTH
InMemorySessionCoordinator and Stage I2's own RedisSessionCoordinator
(see that file's own module docstring for the full list and reasoning).
The ONE test remaining here,
`test_find_match_delegates_to_an_injected_matchmaking_queue_instance`,
stays because it asserts something only InMemorySessionCoordinator's
own design actually does: delegating to (and letting a caller directly
inspect/mutate) an INJECTED, real `MatchmakingQueue` instance.
RedisSessionCoordinator has no equivalent - it queries a Redis sorted
set directly, with no injected collaborator object for this same kind
of delegation assertion to target - so this test has no Redis-side
counterpart and is not parameterized.
"""

from __future__ import annotations

from server.application.matchmaking_queue import MatchmakingQueue
from server.application.session_coordinator import InMemorySessionCoordinator


class _FakeClock:
    """Same settable fake clock shape as test_matchmaking_queue.py's own
    _FakeClock - injected here via a real MatchmakingQueue so tests never
    depend on real elapsed time."""

    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def test_find_match_delegates_to_an_injected_matchmaking_queue_instance():
    clock = _FakeClock(100.0)
    queue = MatchmakingQueue(clock=clock)
    coordinator = InMemorySessionCoordinator(matchmaking_queue=queue)

    coordinator.find_match(connection_id="conn-a", username="alice", rating=1200)

    # The injected queue instance itself was genuinely mutated - proves
    # this is delegation, not a separately-reimplemented queue.
    clock.value = 161.0
    expired = queue.expire_timed_out(now=clock.value, timeout_seconds=60)
    assert [entry.connection_id for entry in expired] == ["conn-a"]
