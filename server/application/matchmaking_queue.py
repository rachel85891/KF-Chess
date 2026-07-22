"""matchmaking_queue.py: Stage E1 ("Play button" - CTD26 slides' own
"search for an opponent within ELO±100, one-minute timeout" framing) -
a standalone, in-memory matchmaking queue: waiting players, paired by
rating, expired by real elapsed time. Built and tested COMPLETELY IN
ISOLATION from networking/GameSession/GameServer, mirroring this
project's own established pattern of proving a new capability correct
on its own before wiring it into the protocol (Stage D1's
UserRepository before Stage D2's GameServer wiring; Stage B2's
GameSession before Stage B3's GameServer wiring). Wiring this into the
real connect-time protocol is explicitly server/application/
game_server.py's own job, not this module's - this class has never
heard of a ServerConnection, an AUTH command, or a wire message.

RATING RANGE - INCLUSIVE OF EXACTLY 100 (per this stage's own
"within ELO±100" requirement): two ratings that differ by EXACTLY 100
are a valid match (`abs(a.rating - b.rating) <= 100`, not `< 100`) -
re-verified directly against the task's own "returns the first pair
whose ratings differ by at most 100 (inclusive)" wording.

PAIRING STRATEGY - EARLIEST-JOINED-FIRST (FIFO FAIRNESS), NOT
CLOSEST-RATING-FIRST (a real, documented choice, per this stage's own
explicit "decide and document" requirement): find_match() iterates
waiting entries in JOIN ORDER and, for each one (starting from the
OLDEST), scans the REMAINING entries - also in join order - for the
FIRST one within 100 rating points; the first such pair found is
returned. This means: (1) the OLDEST waiting player is always included
in the match found, if ANY compatible partner exists for them at all -
never skipped over in favor of matching two younger entries together
first, even if one of those younger entries happens to be a CLOSER
rating match for someone else; (2) among several partners compatible
with a given player, the EARLIEST-JOINED one is chosen, never the
closest-RATED one. WHY FAIRNESS OVER MATCH QUALITY: this stage's own
"one-minute timeout" requirement exists specifically to bound how long
a real player waits - a strategy that always holds out for the
numerically closest possible rating match, at the expense of pairing
the person who has already waited longest, would work AGAINST that
same bound (a already-long-waiting player could keep getting passed
over indefinitely in favor of fresher, better-matched pairs forming
around them). Preferring to satisfy the OLDEST waiting entry first -
with whichever compatible partner is available soonest - directly
serves "nobody waits longer than they have to" as the primary goal,
treating "closest possible rating" as secondary to "already waited the
longest gets priority." A real matchmaking system with more players
waiting could of course use a fancier weighted strategy (widening the
acceptable range the longer someone waits, for example) - explicitly
out of this stage's own scope; the fixed ±100 range plus FIFO fairness
is the simplest strategy that already satisfies every requirement this
stage actually states.

WHY add_waiting_player TAKES NO EXPLICIT `joined_at` PARAMETER, EVEN
THOUGH THE TASK'S OWN WORDING LISTS ONE: mirrors this project's own
already-established "inject the CLOCK callable, not a raw timestamp
from every caller" convention (NetworkGameLoopRunner's own injectable
`clock: Callable[[], float] = time.perf_counter` parameter, Stage
B7.5) - the constructor accepts `clock`, defaulting to the real
`time.perf_counter`, and add_waiting_player calls `self._clock()`
itself to stamp `joined_at` - giving tests a single, directly-settable
fake clock to control every entry's own timestamp deterministically,
rather than requiring every call site to separately compute and pass
"now" itself.

WHY expire_timed_out TAKES `now` AS AN EXPLICIT PARAMETER, UNLIKE
add_waiting_player's OWN INTERNAL CLOCK READ: the caller (GameServer's
own periodic tick-loop check) already has its own freshly-measured
"now" value on hand at the exact moment it calls this method (the same
real-time value it already uses to advance every active match's own
GameSession.wait(delta_ms) call) - accepting it explicitly avoids this
class needing a SECOND clock read of its own that could, in principle,
disagree by a few microseconds with the caller's already-measured
value; the two are guaranteed consistent by construction when the
caller passes its own already-known "now" straight through, which is
exactly what the task's own literal `expire_timed_out(now, ...)`
signature asks for.

find_match() IS READ-ONLY, NEVER MUTATES THE QUEUE (a deliberate SRP
choice, mirrored from remove()'s own separate existence): callers
(GameServer) are expected to call `remove()` for BOTH matched entries
themselves, immediately after consuming a match - keeping "find a
candidate pair" and "commit to consuming it" as two separate, composable
steps, rather than an all-in-one method that decides FOR the caller
when a match is truly "used up" (e.g. a caller could, in principle,
inspect a candidate pair and decide NOT to consume it for some reason,
without this class needing an "undo" mechanism of its own).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

_DEFAULT_RATING_RANGE = 100


@dataclass(frozen=True)
class WaitingPlayer:
    """One waiting entry - a plain data holder, per this project's own
    established frozen-dataclass-for-parsed-results convention (e.g.
    server/presentation/move_command.py's own ParsedMoveCommand)."""

    connection_id: object
    username: str
    rating: int
    joined_at: float


class MatchmakingQueue:
    """A pure, in-memory matchmaking queue - see module docstring for
    the full reasoning behind every decision below. No networking, no
    GameSession/GameServer knowledge, no I/O of any kind."""

    def __init__(self, clock: Callable[[], float] = time.perf_counter) -> None:
        """Create an empty queue.

        Args:
            clock: Callable returning the current time as a float -
                defaults to time.perf_counter (this project's own
                established real-elapsed-time convention). Injectable
                (DIP) purely so tests can supply a controllable, fake
                time source instead of a real sleep - see module
                docstring's own reasoning. Only ever used for measuring
                ELAPSED time (a later call minus an earlier one), never
                compared against any absolute/wall-clock meaning, so
                any monotonically comparable float source works.

        Returns:
            None.
        """

        self._clock = clock
        # A plain dict, keyed by connection_id - Python dicts preserve
        # insertion order (3.7+), which is exactly the JOIN ORDER
        # find_match's own pairing strategy needs to iterate in; O(1)
        # removal by connection_id for remove()/expire_timed_out.
        self._waiting: Dict[object, WaitingPlayer] = {}

    def add_waiting_player(self, connection_id: object, username: str, rating: int) -> None:
        """Add a new waiting entry, timestamped with the current time
        (see module docstring for why this reads self._clock() itself
        rather than accepting a `joined_at` parameter).

        Args:
            connection_id: Any hashable value identifying this waiting
                player - this class never inspects or interprets it
                beyond using it as a dict key (the real caller,
                GameServer, uses the actual ServerConnection object
                itself; this class stays completely networking-
                agnostic and never needs to know that).
            username: The waiting player's username - carried through
                purely for the caller's own later use (e.g. logging,
                or a future stage's own "who did you play" history);
                this class never inspects it.
            rating: The waiting player's current rating - the one field
                find_match's own pairing logic actually reads.

        Returns:
            None.

        Adding the SAME connection_id twice simply overwrites the
        earlier entry (including its own joined_at) - not a scenario
        any real caller has a reason to trigger, so no special error
        handling is added for it.
        """

        self._waiting[connection_id] = WaitingPlayer(
            connection_id=connection_id, username=username, rating=rating, joined_at=self._clock()
        )

    def find_match(self) -> Optional[Tuple[WaitingPlayer, WaitingPlayer]]:
        """Find the first valid pair of waiting entries whose ratings
        differ by at most 100 points - see module docstring's "PAIRING
        STRATEGY" section for the full reasoning behind exactly which
        pair is chosen when more than one valid pair exists.

        Returns:
            (earlier_joined, later_joined) if a valid pair exists;
            None if fewer than two entries are waiting, or no two
            currently-waiting entries are within range of each other.
            Never mutates the queue (see module docstring) - the
            caller must call remove() for both entries itself once it
            has consumed this match.
        """

        entries = list(self._waiting.values())
        for i, first in enumerate(entries):
            for second in entries[i + 1 :]:
                if abs(first.rating - second.rating) <= _DEFAULT_RATING_RANGE:
                    return first, second
        return None

    def remove(self, connection_id: object) -> None:
        """Remove the waiting entry for `connection_id`, if any.

        Args:
            connection_id: The same value originally passed to
                add_waiting_player.

        Returns:
            None.

        Safe to call even if `connection_id` was never added, or has
        already been removed - a discard, not a remove() that raises -
        mirroring server/presentation/connection_manager.py's own
        ConnectionManager.remove and kungfu_chess.bus.EventBus.
        unsubscribe's own identical "no-op, not an error" convention.
        """

        self._waiting.pop(connection_id, None)

    def expire_timed_out(self, now: float, timeout_seconds: float = 60) -> List[WaitingPlayer]:
        """Find, remove, and return every waiting entry that has been
        queued for STRICTLY LONGER than `timeout_seconds`.

        Args:
            now: The caller's own already-measured current time - see
                module docstring for why this is an explicit parameter,
                unlike add_waiting_player's own internal clock read.
            timeout_seconds: How long an entry may wait before it is
                considered expired. Defaults to 60 (this stage's own
                "one-minute timeout" requirement) - overridable (e.g. a
                short duration in tests, so no test needs a real
                60-second sleep).

        Returns:
            Every expired entry (possibly empty) - each one is also
            REMOVED from the queue as part of this same call, so a
            second, identical call never returns the same entry twice
            (this method both finds AND commits the removal in one
            step, unlike find_match's own deliberately read-only
            contract - there is no reason a caller would ever want to
            "peek" at an expired entry without also removing it, unlike
            a candidate match, which a caller might reasonably choose
            not to consume).
        """

        expired = [entry for entry in self._waiting.values() if (now - entry.joined_at) > timeout_seconds]
        for entry in expired:
            self._waiting.pop(entry.connection_id, None)
        return expired
