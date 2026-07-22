"""Unit tests for Stage E1's standalone matchmaking queue
(server/application/matchmaking_queue.py) - built and tested COMPLETELY
IN ISOLATION from networking/GameSession, mirroring this project's own
established pattern of proving a new capability correct on its own
before wiring it into the protocol (Stage D1's UserRepository before
Stage D2's GameServer wiring; Stage B2's GameSession before Stage B3's
GameServer wiring). No real clock, no real sleeps - a fake, settable
clock throughout, mirroring NetworkGameLoopRunner's own established
Stage B7.5 "inject the clock" convention.
"""

from __future__ import annotations

from server.application.matchmaking_queue import MatchmakingQueue, WaitingPlayer


class _FakeClock:
    """A settable fake clock - the same shape this project's own
    pixel-sliding/cooldown tests already use for NetworkGameLoopRunner's
    injectable `clock` parameter (a plain callable, here backed by a
    directly-settable `.value`)."""

    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def test_add_waiting_player_stores_the_entrys_own_fields():
    clock = _FakeClock(100.0)
    queue = MatchmakingQueue(clock=clock)

    queue.add_waiting_player("conn-a", "alice", 1200)

    # No public "get" accessor is needed beyond find_match/expire_timed_out
    # - proven indirectly via expire_timed_out, which must surface this
    # entry with the correct joined_at (the clock's value AT THE TIME OF
    # add_waiting_player, not whenever it's later queried).
    clock.value = 100.0 + 61
    expired = queue.expire_timed_out(now=clock.value, timeout_seconds=60)

    assert len(expired) == 1
    assert expired[0] == WaitingPlayer(connection_id="conn-a", username="alice", rating=1200, joined_at=100.0)


def test_find_match_returns_none_when_fewer_than_two_players_are_waiting():
    queue = MatchmakingQueue(clock=_FakeClock())
    queue.add_waiting_player("conn-a", "alice", 1200)

    assert queue.find_match() is None


def test_find_match_pairs_two_players_within_100_rating_points_inclusive():
    queue = MatchmakingQueue(clock=_FakeClock())
    queue.add_waiting_player("conn-a", "alice", 1200)
    queue.add_waiting_player("conn-b", "bob", 1300)  # exactly 100 apart

    match = queue.find_match()

    assert match is not None
    a, b = match
    assert a.connection_id == "conn-a"
    assert b.connection_id == "conn-b"


def test_find_match_returns_none_when_the_only_two_players_differ_by_more_than_100():
    queue = MatchmakingQueue(clock=_FakeClock())
    queue.add_waiting_player("conn-a", "alice", 1200)
    queue.add_waiting_player("conn-b", "bob", 1301)  # 101 apart - just outside range

    assert queue.find_match() is None


def test_find_match_does_not_mutate_the_queue_callers_must_call_remove_themselves():
    queue = MatchmakingQueue(clock=_FakeClock())
    queue.add_waiting_player("conn-a", "alice", 1200)
    queue.add_waiting_player("conn-b", "bob", 1250)

    first_call = queue.find_match()
    second_call = queue.find_match()

    assert first_call == second_call  # still there, unremoved


def test_find_match_prefers_the_earliest_joined_player_and_their_earliest_compatible_partner():
    # Pairing strategy (documented in matchmaking_queue.py's own module
    # docstring): fairness/FIFO over "best" rating match - the OLDEST
    # waiting player is always included in the first match found if ANY
    # compatible partner exists for them, and among multiple compatible
    # partners, the one who ALSO joined earliest is chosen - never the
    # closest-rated one if that means skipping over someone who has
    # already waited longer.
    clock = _FakeClock(0.0)
    queue = MatchmakingQueue(clock=clock)

    clock.value = 0.0
    queue.add_waiting_player("conn-a", "alice", 1200)  # joins first
    clock.value = 1.0
    queue.add_waiting_player("conn-b", "bob", 1150)  # joins second, compatible with alice (50 apart)
    clock.value = 2.0
    queue.add_waiting_player("conn-c", "carol", 1195)  # joins third, CLOSER to alice's rating (5 apart) than bob is

    match = queue.find_match()

    # Alice (oldest) is matched with Bob (her earliest-joined compatible
    # partner), NOT Carol - even though Carol is a closer rating match -
    # because Bob joined the queue before Carol did.
    assert match is not None
    a, b = match
    assert a.username == "alice"
    assert b.username == "bob"


def test_find_match_still_pairs_two_later_players_when_the_oldest_has_no_compatible_partner():
    clock = _FakeClock(0.0)
    queue = MatchmakingQueue(clock=clock)

    queue.add_waiting_player("conn-a", "alice", 1200)  # no one else is within 100 of alice
    queue.add_waiting_player("conn-b", "bob", 1500)
    queue.add_waiting_player("conn-c", "carol", 1550)  # 50 apart from bob - a valid pair

    match = queue.find_match()

    assert match is not None
    a, b = match
    assert a.username == "bob"
    assert b.username == "carol"


def test_remove_deletes_the_entry_so_it_is_no_longer_matchable_or_expirable():
    clock = _FakeClock(0.0)
    queue = MatchmakingQueue(clock=clock)
    queue.add_waiting_player("conn-a", "alice", 1200)
    queue.add_waiting_player("conn-b", "bob", 1210)

    queue.remove("conn-a")

    assert queue.find_match() is None  # only bob remains - no pair possible
    clock.value = 1000.0
    assert queue.expire_timed_out(now=clock.value, timeout_seconds=1) == [
        WaitingPlayer(connection_id="conn-b", username="bob", rating=1210, joined_at=0.0)
    ]


def test_remove_is_a_safe_no_op_for_an_unknown_connection_id():
    queue = MatchmakingQueue(clock=_FakeClock())

    queue.remove("never-added")  # must not raise


def test_expire_timed_out_returns_and_removes_only_entries_past_the_timeout():
    clock = _FakeClock(0.0)
    queue = MatchmakingQueue(clock=clock)
    queue.add_waiting_player("conn-old", "alice", 1200)

    clock.value = 30.0
    queue.add_waiting_player("conn-new", "bob", 9999)  # far rating - never matches alice

    clock.value = 61.0  # alice has waited 61s, bob only 31s
    expired = queue.expire_timed_out(now=clock.value, timeout_seconds=60)

    assert [entry.connection_id for entry in expired] == ["conn-old"]
    # The still-fresh entry remains queued, unaffected.
    clock.value = 91.0  # now bob has waited 61s too
    expired_again = queue.expire_timed_out(now=clock.value, timeout_seconds=60)
    assert [entry.connection_id for entry in expired_again] == ["conn-new"]


def test_expire_timed_out_uses_strictly_greater_than_not_greater_or_equal():
    clock = _FakeClock(0.0)
    queue = MatchmakingQueue(clock=clock)
    queue.add_waiting_player("conn-a", "alice", 1200)

    clock.value = 60.0  # exactly at the timeout boundary, not yet OVER it
    assert queue.expire_timed_out(now=clock.value, timeout_seconds=60) == []

    clock.value = 60.0001
    expired = queue.expire_timed_out(now=clock.value, timeout_seconds=60)
    assert [entry.connection_id for entry in expired] == ["conn-a"]


def test_expire_timed_out_removes_entries_from_the_queue_so_they_are_not_returned_twice():
    clock = _FakeClock(0.0)
    queue = MatchmakingQueue(clock=clock)
    queue.add_waiting_player("conn-a", "alice", 1200)

    clock.value = 100.0
    first = queue.expire_timed_out(now=clock.value, timeout_seconds=60)
    second = queue.expire_timed_out(now=clock.value, timeout_seconds=60)

    assert len(first) == 1
    assert second == []
