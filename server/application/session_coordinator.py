"""session_coordinator.py: Stage F2 of the Rooms/Viewers track - a
SessionCoordinator Protocol unifying matchmaking (Stage E1's existing
MatchmakingQueue) and rooms (Stage F1's existing Room/RoomCodeGenerator)
behind one shared interface, plus ONE concrete, in-memory implementation
(InMemorySessionCoordinator) that WRAPS both existing collaborators
rather than reimplementing either's own already-tested logic. Built and
tested COMPLETELY IN ISOLATION, mirroring matchmaking_queue.py's and
room.py's own established pattern of proving a new capability correct on
its own before wiring it into anything - GameServer is NOT touched by
this stage (see room.py's own "WHY THIS STAGE DOES NOT BUILD A ROOM
REGISTRY" section, which already named this exact stage as the reason it
deferred that responsibility).

WHY A PROTOCOL (SHARED INTERFACE) INSTEAD OF GameServer TALKING DIRECTLY
TO A MatchmakingQueue AND A Room DICT ITSELF: today, "who's matched with
whom" (MatchmakingQueue's own plain `Dict[object, WaitingPlayer]`) and
"who's in which room" (a hypothetical `Dict[RoomCode, Room]`, per room.py's
own deferred-registry note) are each a plain, in-process Python
collection - correct and sufficient for a single server instance, but
this project has a concrete, near-term plan to run MULTIPLE SERVER
INSTANCES, at which point "who's matched with whom"/"who's in which
room" can no longer live in any ONE process's own memory at all - a
second server instance would have no way to see the first instance's own
dicts. A Protocol-shaped seam, sitting between GameServer and this
coordination state, is what makes THAT eventual swap possible without
GameServer (or anything else that calls `find_match`/`create_room`/
`join_room`) ever needing to change again when it happens - exactly the
same reason ProtocolHandler exists as its own class rather than
GameServer inlining every wire-format detail itself (see
server/application/game_server.py's own "THE APPLICATION/PRESENTATION
BOUNDARY" docstring section for the identical underlying argument,
applied here to a different boundary).

WHAT A FUTURE DISTRIBUTED IMPLEMENTATION WOULD NEED TO SATISFY (fully
specified here, NOT built - that is explicitly a future stage's job, not
this one): a Redis- or database-backed SessionCoordinator would need
`find_match` to atomically enqueue-and-attempt-pairing against a SHARED
store visible to every server process (e.g. a Redis sorted set keyed by
rating, with a Lua script or transaction making "check for a compatible
partner, then remove both" atomic across processes - the same
read-then-commit split MatchmakingQueue's own find_match()/remove() pair
already keeps as two steps, just now needing real cross-process
atomicity instead of relying on asyncio's single-threaded cooperative
scheduling, see game_server.py's own "WHY THE OLD self._join_lock...
IS REMOVED" section for why that in-process assumption is what a
distributed store could no longer take for granted); `create_room` would
need real collision detection against every OTHER instance's own active
room codes (this module's own in-memory implementation already includes
this - see below - specifically BECAUSE it is the one piece of "future
implementation" behavior a single process CAN already provide correctly
today, room.py's own docstring having explicitly deferred it here);
`join_room` would need the SAME Room object's state (or an equivalent
serialized snapshot) to be visible and consistently mutated regardless
of WHICH server process happens to handle a given join request. None of
this changes the Protocol's own method signatures below at all - that is
the entire point of designing them against this module's own real,
already-established data shapes (WaitingPlayer, Room, Role) now, rather
than against this in-memory implementation's own internal Dict, which a
distributed implementation would replace entirely.

PROTOCOL, NOT ABC: this project has no existing ABC-based interface
anywhere to mirror (re-verified directly - grep across server/ finds
zero `abc.ABC`/`abstractmethod` usage); it DOES already have an
established structural-typing-flavored convention for "the thing that
varies is whatever exposes the right shape" (MatchmakingQueue's own
injectable `clock: Callable[[], float]`, RoomCodeGenerator's own
injectable `random_source` needing only a `.choice(sequence)` method) -
`typing.Protocol` is the natural generalization of that SAME convention
to a multi-method interface: a future distributed implementation needs
only to expose the right three methods, never to import this module or
subclass anything from it (a real, meaningful property once "future
implementation" might reasonably live in a completely separate package,
e.g. a `session_coordinator_redis` module with no reason to depend on
this one at all). `@runtime_checkable` is added purely so this module's
own conformance test can assert a real, structural `isinstance(...,
SessionCoordinator)` check (the task's own required test) - it does not
change the Protocol's own static-typing behavior at all, only enables
that one runtime check.

find_match's OWN SIGNATURE NECESSARILY TAKES connection_id/username/
rating, NOT JUST A BARE rating: WaitingPlayer (MatchmakingQueue's own
already-established shape, reused here verbatim, per this stage's own
"do not invent parallel data types" requirement) requires all three
fields to construct a queue entry at all - a coordinator method that
accepted only a rating would have nothing to actually enqueue.
MatchResult is a type alias for MatchmakingQueue.find_match()'s own
already-existing `Tuple[WaitingPlayer, WaitingPlayer]` return shape -
named for this Protocol's own readability, not a new competing dataclass
wrapping it.

WHY find_match DOES add_waiting_player + find_match + remove IN ONE
CALL, RETURNING A RESULT ONLY TO THE CALLER WHOSE OWN ENTRY WAS ACTUALLY
PAIRED: this mirrors GameServer's own real `_wait_for_match`/
`_attempt_matchmaking` combination (add, then attempt to pair) collapsed
into one synchronous call, appropriate for THIS module's own explicit
scope (a synchronous facade, not a second async/futures-based waiting
mechanism duplicating GameServer's own - that machinery stays exactly
where it already is, untouched, since this stage does not wire anything
into GameServer at all). Critically, if MatchmakingQueue.find_match()
happens to return a pair that does NOT include the just-added
connection_id (a real, possible outcome per that method's own documented
FIFO-fairness pairing strategy - an older, unrelated pair may already be
valid), this method deliberately does NOT remove or claim that other
pair - it returns None, leaving every entry (including the caller's own,
and the other pair still untouched) exactly as MatchmakingQueue itself
already left them, and the queue's own state remains fully correct for
whichever future call eventually completes each real pairing. This
avoids a genuine correctness trap a naive "always drain and return
whatever pair find_match() gives me" implementation would fall into:
silently consuming and discarding a pairing between two OTHER
participants that this caller has no way to hand back to them.

create_room DOES DETECT AND RE-ROLL ON A CODE COLLISION - room.py'S OWN
DEFERRED RESPONSIBILITY, NOW FULFILLED HERE: RoomCodeGenerator.generate()
makes no uniqueness guarantee of its own (see that module's own "WHY
THIS MODULE NEVER CHECKS FOR CODE UNIQUENESS" section, which explicitly
named "a future coordinator, which DOES have the full set of active
codes to check against" as the right place for this) - this
implementation's own `self._rooms: Dict[RoomCode, Room]` is exactly that
full set, so `create_room` re-generates until it finds a code not
already present as a key, satisfying that deferred requirement without
RoomCodeGenerator itself ever needing to change.

join_room's RoomJoinResult PAIRS THE ROOM WITH THE ROLE JUST ASSIGNED:
Room.add_player()/add_viewer() (Stage F1, reused verbatim, unmodified)
are both void methods - this coordinator is the one place that decides
GUEST-vs-VIEWER (via Room's own already-tested `can_add_player()` query,
exactly mirroring `_attempt_matchmaking`'s own "query, then commit" use
of MatchmakingQueue.find_match()) and needs to report back which one it
chose, information Room itself has no reason to return from either add
method. `None` (not an exception) is returned for an unknown room code -
mirroring server/persistence/user_repository.py's own established
bool/None-vs-exception convention for an ordinary, expected "not found"
outcome that isn't a caller-side precondition violation the way
RoomFullError's own real trigger condition is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Protocol, Tuple, runtime_checkable

from server.application.matchmaking_queue import MatchmakingQueue, WaitingPlayer
from server.application.room import Role, Room, RoomCodeGenerator

# Type aliases, not new competing dataclasses - see module docstring's
# "find_match's OWN SIGNATURE..." section for why these simply NAME
# MatchmakingQueue's/Room's own already-existing real shapes rather than
# wrapping them in something new.
RoomCode = str
MatchResult = Tuple[WaitingPlayer, WaitingPlayer]


@dataclass(frozen=True)
class RoomJoinResult:
    """The outcome of a successful join_room call - see module
    docstring's "join_room's RoomJoinResult..." section for why this
    pairing (not a bare Role, not a bare Room) is what a caller actually
    needs back."""

    room: Room
    role: Role


@runtime_checkable
class SessionCoordinator(Protocol):
    """The shared interface unifying matchmaking and rooms - see module
    docstring for the full reasoning behind every decision below. A
    structural Protocol, not a base class: nothing needs to import or
    subclass this to satisfy it (see module docstring's "PROTOCOL, NOT
    ABC" section)."""

    def find_match(self, connection_id: object, username: str, rating: int) -> Optional[MatchResult]:
        """Enqueue this participant (via MatchmakingQueue.
        add_waiting_player) and attempt to pair it.

        Args:
            connection_id: Any hashable value identifying this waiting
                participant - same agnostic-identity convention as
                MatchmakingQueue.add_waiting_player's own parameter.
            username: This participant's username.
            rating: This participant's current rating.

        Returns:
            (earlier_joined, later_joined) ONLY if THIS participant's own
            entry ended up in the pair found; None if no compatible
            partner is available yet (this participant remains queued -
            see module docstring's "WHY find_match DOES..." section for
            why a pair not involving this caller is never claimed here).
        """

    def create_room(self, host_identity: object) -> RoomCode:
        """Create a brand new room with `host_identity` as its host.

        Args:
            host_identity: Any value identifying the host - same
                agnostic-identity convention as Room.__init__'s own
                `host_identity` parameter.

        Returns:
            The new room's own real, unique code (see module docstring's
            "create_room DOES DETECT AND RE-ROLL..." section).
        """

    def join_room(self, code: RoomCode, identity: object) -> Optional[RoomJoinResult]:
        """Join an existing room, as a GUEST if a player slot is open,
        else as a VIEWER (per Room's own existing capacity rules).

        Args:
            code: A room code, as previously returned by create_room.
            identity: Any value identifying the joining participant.

        Returns:
            The RoomJoinResult (which role was assigned, and the real
            Room now containing this member) if `code` names a real,
            currently-tracked room; None if it does not (see module
            docstring's "join_room's RoomJoinResult..." section for why
            this is a plain None, not an exception).
        """


class InMemorySessionCoordinator:
    """The one concrete SessionCoordinator implementation this stage
    builds - composes a REAL MatchmakingQueue and a REAL
    Dict[RoomCode, Room] of REAL Room instances, wrapping both rather
    than reimplementing either's own logic. See module docstring for the
    full reasoning behind every decision below. Satisfies the
    SessionCoordinator Protocol structurally - never declared as a
    subclass of it (see that Protocol's own docstring)."""

    def __init__(
        self,
        matchmaking_queue: Optional[MatchmakingQueue] = None,
        room_code_generator: Optional[RoomCodeGenerator] = None,
    ) -> None:
        """Create a coordinator.

        Args:
            matchmaking_queue: The MatchmakingQueue this instance
                delegates matchmaking to. Defaults to a fresh, real
                MatchmakingQueue - injectable (DIP) for tests that want
                to control (or directly inspect) the queue.
            room_code_generator: The RoomCodeGenerator this instance
                delegates room-code generation to. Defaults to a fresh,
                real RoomCodeGenerator - injectable (DIP) for tests that
                want deterministic codes.

        Returns:
            None.
        """

        self._matchmaking_queue = matchmaking_queue if matchmaking_queue is not None else MatchmakingQueue()
        self._room_code_generator = room_code_generator if room_code_generator is not None else RoomCodeGenerator()
        # See module docstring's "create_room DOES DETECT AND RE-ROLL..."
        # section - this Dict IS the "full set of active codes" a future
        # coordinator needs, that RoomCodeGenerator itself deliberately
        # never had access to.
        self._rooms: Dict[RoomCode, Room] = {}

    def find_match(self, connection_id: object, username: str, rating: int) -> Optional[MatchResult]:
        """See SessionCoordinator.find_match's own docstring - this is a
        thin wrapper: every actual pairing decision is
        MatchmakingQueue.find_match's own, unmodified."""

        self._matchmaking_queue.add_waiting_player(connection_id, username, rating)

        pair = self._matchmaking_queue.find_match()
        if pair is None:
            return None

        first, second = pair
        if connection_id not in (first.connection_id, second.connection_id):
            # A different, already-waiting pair is valid first - see
            # module docstring's "WHY find_match DOES..." section: never
            # claimed on this caller's behalf, queue left untouched.
            return None

        self._matchmaking_queue.remove(first.connection_id)
        self._matchmaking_queue.remove(second.connection_id)
        return pair

    def create_room(self, host_identity: object) -> RoomCode:
        """See SessionCoordinator.create_room's own docstring."""

        code = self._room_code_generator.generate()
        while code in self._rooms:
            code = self._room_code_generator.generate()

        self._rooms[code] = Room(code=code, host_identity=host_identity)
        return code

    def join_room(self, code: RoomCode, identity: object) -> Optional[RoomJoinResult]:
        """See SessionCoordinator.join_room's own docstring - GUEST-vs-
        VIEWER is decided via Room.can_add_player(), its own existing,
        already-tested capacity rule, never reimplemented here."""

        room = self._rooms.get(code)
        if room is None:
            return None

        if room.can_add_player():
            room.add_player(identity)
            return RoomJoinResult(room=room, role=Role.GUEST)

        room.add_viewer(identity)
        return RoomJoinResult(room=room, role=Role.VIEWER)
