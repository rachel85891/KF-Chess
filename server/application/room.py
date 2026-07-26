"""room.py: Stage F1 of the Rooms/Viewers track - a RoomCode generator
and a pure, in-memory Room data structure. Built and tested COMPLETELY
IN ISOLATION from networking/GameSession/GameServer, mirroring
server/application/matchmaking_queue.py's own established pattern of
proving a new coordination concept correct on its own before wiring it
into anything (that module's own docstring cites Stage D1's
UserRepository before Stage D2's GameServer wiring, and Stage B2's
GameSession before Stage B3's GameServer wiring, as the identical
earlier precedents this stage now follows for Rooms). This module has
never heard of a ServerConnection, a wire message, or GameServer's own
existing `_matches`/`_matchmaking_queue` composition.

WHY THIS STAGE DOES NOT BUILD A ROOM REGISTRY (a `Dict[code, Room]`
manager), AND WHY THAT IS DELIBERATE, NOT AN OVERSIGHT: a registry is a
COORDINATION responsibility - deciding how many rooms exist at once,
looking one up by its code, deciding what happens when a code collides
with an already-active room - genuinely analogous to what GameServer's
own `_matchmaking_queue`/`_matches` composition already does for
matchmaking (see that class's own module docstring). This project has
a concrete, near-term plan to unify THAT existing coordination
responsibility (today, matchmaking only) with this new one (rooms)
behind a SHARED abstraction - a `SessionCoordinator` Protocol, arriving
in Stage F2, not this one - specifically because a future stage of this
project intends to run MULTIPLE SERVER INSTANCES rather than one single
process holding all coordination state in plain Python dicts, and a
Protocol-shaped seam is what makes that swap possible later (e.g. a
Redis- or database-backed coordinator implementing the same Protocol)
without every CALLER of "find/track a room or a match" needing to change
again when that swap happens. Building a registry NOW, ahead of that
Protocol existing, would mean either building throwaway coordination
code Stage F2 immediately replaces, or reverse-engineering Stage F2's
own eventual interface shape prematurely from inside a task that was
never asked to design it - this stage's own explicit scope boundary is
narrower and more durable: prove "what is a Room, and how do I generate
a code for one" completely on its own, exactly as MatchmakingQueue
proved "how do I pair two waiting entries" on its own before Stage E1's
GameServer ever wired it to a connection.

ROOM CODE ALPHABET - EXCLUDES VISUALLY AMBIGUOUS CHARACTERS (a real,
documented usability choice, not an arbitrary restriction): a room code
exists to be read off one player's own screen and TYPED by a second,
different human into another client - `0`/`O` and `1`/`I` are the
classic, well-known ambiguous-glyph pairs in most sans-serif UI fonts
(exactly the same real-world concern many production systems, from
Zoom meeting IDs to license-plate/serial-number schemes, already design
around). ROOM_CODE_ALPHABET therefore omits `0`, `O`, `1`, and `I`
entirely (uppercase letters A-Z minus I/O, plus digits 2-9), rather
than including the full 36-character alphanumeric set - a strictly
smaller, but strictly less error-prone-to-transcribe, character space.
ROOM_CODE_LENGTH = 6 is a named constant (never hardcoded at any other
call site) - with the resulting 32-character alphabet, 32**6 (roughly
1.07 billion) possible codes is far more than enough headroom for this
project's own realistic concurrent-room scale, without this module
needing to reason about collision probability at all (see below for
why collision handling is explicitly not this module's job).

WHY THIS MODULE NEVER CHECKS FOR CODE UNIQUENESS: RoomCodeGenerator
produces a random code - it has no registry of "which codes are
currently taken" to check against (see the "NO ROOM REGISTRY" section
above for why that registry doesn't exist yet, deliberately). Detecting
and re-rolling a collision against a real, already-active set of rooms
is therefore necessarily a Stage F2 SessionCoordinator concern, not
something this stage could correctly implement even if it tried to -
re-verified directly: the 32**6 code space makes a real collision
already vanishingly unlikely at any scale this project is likely to
reach in practice, but that likelihood argument is exactly why a
FUTURE coordinator (which DOES have the full set of active codes to
check against) is the right, and only structurally possible, place to
add a real "regenerate on collision" retry loop, not this one.

INJECTABLE RANDOMNESS (mirrors MatchmakingQueue's own injectable
`clock: Callable[[], float]` constructor parameter exactly, applied
here to `random_source: random.Random` instead): a real, uninjected
`random.Random()` instance is used by default in production; a test
supplies its own instance instead (either a real, SEEDED
`random.Random(seed)` for a reproducible-but-still-random sequence, or
a plain fake object exposing the one method this class actually calls,
`.choice(sequence)`) - the same "inject the thing that varies" DIP
convention this whole project already applies everywhere it has a real
source of non-determinism to control in tests (this project's own
established precedent list already includes NetworkGameLoopRunner's
`clock`, MatchmakingQueue's `clock`, and now this).

Role IS A PLAIN, THREE-VALUE Enum (HOST/GUEST/VIEWER), MIRRORING
kungfu_chess.model.color.Color's OWN SHAPE EXACTLY (a bare `Enum`
subclass, short string values, no behavior beyond identity) - the
established, minimal-ceremony convention this project already uses for
every other small, closed set of named alternatives, not a new pattern
invented for this stage.

Room IS DELIBERATELY A SINGLE, UNIFIED LIST OF (identity, role) PAIRS
(`RoomMember`), NOT THREE SEPARATE FIELDS (`host`/`guest`/`viewers`):
"who is in this room, and in what capacity" is genuinely ONE concept
with a role attached, not three independent concerns that happen to
co-exist - a single `_members: List[RoomMember]` list (insertion-
ordered: the host is always first, exactly one guest may follow, any
number of viewers may follow that) is both the simplest possible
representation and the one that scales cleanly to "however many
viewers happen to be watching right now," which is exactly this
stage's own explicit, forward-looking requirement (Stage F6 will need
an already-correct, already-tested "arbitrary, changing number of
viewers" contract to build on - re-verified directly, in every test in
this module's own test suite, that no method here ever hardcodes a
viewer-count ceiling of any kind).

CAPACITY IS ENFORCED ONLY FOR PLAYERS (HOST + AT MOST ONE GUEST),
NEVER FOR VIEWERS: `can_add_player()`/`add_player()` together enforce
the real 1-vs-1 shape this project's own chess variant actually needs
(exactly two real players per game, matching every other stage's own
"two matched players" assumption, e.g. MatchmakingQueue's own pairing
contract) - `add_player()` raises `RoomFullError` (mirrors
server/persistence/user_repository.py's own "raise a clear, specific
error for a caller-side precondition violation" convention, e.g.
UserNotFoundError) if called when a host and a guest already both
occupy the room, rather than silently doing nothing or silently
overwriting the existing guest - a caller is expected to check
`can_add_player()` (or catch this exception) before ever calling
`add_player()`, the same "read-only query, separate from the mutating
commit" split MatchmakingQueue's own find_match()/remove() pair already
establishes. `add_viewer()`, by contrast, has NO capacity check and
NO exception path at all - it is an unconditional append, by design,
since there is no real-world upper bound on how many people may watch
a game.

`players()`/`viewers()` RETURN DEFENSIVE COPIES (`tuple(...)`), NEVER
THE LIVE INTERNAL LIST: mirrors MatchmakingQueue.find_match()'s own
`list(self._waiting.values())` defensive-copy convention - a caller
holding onto an earlier snapshot must never see it silently change
underneath it because this Room was mutated afterward elsewhere.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple

# See module docstring's "ROOM CODE ALPHABET" section - uppercase
# letters A-Z minus the visually-ambiguous I/O, plus digits 2-9 (0/1
# omitted for the identical reason). 32 characters total.
ROOM_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
ROOM_CODE_LENGTH = 6


class RoomCodeGenerator:
    """Generates random, human-typeable room codes - see module
    docstring for the full reasoning behind every decision below."""

    def __init__(self, random_source: Optional[random.Random] = None) -> None:
        """Create a generator.

        Args:
            random_source: An object exposing a `choice(sequence)`
                method (real `random.Random` instances already do -
                `random.Random` itself, not the top-level `random`
                module's own free functions, since an INSTANCE is what
                lets two independently-constructed generators each hold
                their own, separately-seedable state). Defaults to a
                fresh, real `random.Random()` - injectable (DIP) purely
                so tests can supply a seeded or fully deterministic fake
                instead, mirroring MatchmakingQueue's own injectable
                `clock` parameter.

        Returns:
            None.
        """

        self._random_source = random_source if random_source is not None else random.Random()

    def generate(self) -> str:
        """Generate one random room code.

        Returns:
            A string of exactly ROOM_CODE_LENGTH characters, each drawn
            from ROOM_CODE_ALPHABET - see module docstring's "WHY THIS
            MODULE NEVER CHECKS FOR CODE UNIQUENESS" section: this
            method makes no uniqueness guarantee of any kind, purely by
            design (there is no registry here to check against).
        """

        return "".join(self._random_source.choice(ROOM_CODE_ALPHABET) for _ in range(ROOM_CODE_LENGTH))


class Role(Enum):
    """The three capacities a room member can hold - mirrors
    kungfu_chess.model.color.Color's own bare-Enum shape exactly (see
    module docstring)."""

    HOST = "host"
    GUEST = "guest"
    VIEWER = "viewer"


@dataclass(frozen=True)
class RoomMember:
    """One room member - a plain data holder, per this project's own
    established frozen-dataclass-for-parsed-results convention (e.g.
    server/application/matchmaking_queue.py's own WaitingPlayer)."""

    identity: object
    role: Role


class RoomError(Exception):
    """Base class for Room's own errors - mirrors
    server/persistence/user_repository.py's UserRepositoryError and
    kungfu_chess/client/network/network_game_client.py's
    NetworkGameClientError's own identical per-class base-exception
    convention."""


class RoomFullError(RoomError):
    """Raised by add_player() when a host and a guest already both
    occupy the room - see module docstring's "CAPACITY IS ENFORCED
    ONLY FOR PLAYERS" section for the full reasoning behind why this
    raises rather than silently no-op-ing or overwriting."""


class Room:
    """One room's own pure state - see module docstring for the full
    reasoning behind every decision below. No networking, no
    GameSession, no I/O of any kind."""

    def __init__(self, code: str, host_identity: object) -> None:
        """Create a room, already containing exactly its own host - see
        module docstring's own framing: a room is created BY someone
        (the host), who is a member of it from the very first instant
        it exists, never joined later the way a guest/viewer is.

        Args:
            code: This room's own real code (e.g. from
                RoomCodeGenerator.generate()) - this class never
                generates or validates its own code; that is the
                caller's job (and, per module docstring, a FUTURE
                coordinator's job to also guarantee is unique).
            host_identity: Any hashable-or-not value identifying the
                host - this class never inspects or interprets it
                beyond storing it (the real caller might use a
                username, a connection object, or anything else; this
                class stays completely agnostic about what "identity"
                means, the same way MatchmakingQueue's own
                `connection_id: object` field already does).

        Returns:
            None.
        """

        self.code = code
        self._members: List[RoomMember] = [RoomMember(identity=host_identity, role=Role.HOST)]

    def players(self) -> Tuple[RoomMember, ...]:
        """Every real player currently in this room (HOST, and the
        GUEST if one has joined) - in join order, host always first.

        Returns:
            A defensive copy (see module docstring) - never the live
            internal list.
        """

        return tuple(member for member in self._members if member.role in (Role.HOST, Role.GUEST))

    def viewers(self) -> Tuple[RoomMember, ...]:
        """Every viewer currently watching this room, in join order.

        Returns:
            A defensive copy (see module docstring) - never the live
            internal list. Empty (not None) when nobody is watching -
            mirrors this project's own established "empty collection,
            not a sentinel" convention for an absent-but-expected list.
        """

        return tuple(member for member in self._members if member.role is Role.VIEWER)

    def can_add_player(self) -> bool:
        """Whether a real player (a GUEST) could be added right now.

        Returns:
            True only while exactly one real player (the host) is
            present; False once a host AND a guest both already
            occupy the room. Never affected by however many viewers
            are currently present (see module docstring's "CAPACITY IS
            ENFORCED ONLY FOR PLAYERS" section) - viewers never occupy
            or block a player slot.
        """

        return len(self.players()) < 2

    def is_full(self) -> bool:
        """Whether this room already has its full complement of two
        real players (a host and a guest) - the exact negation of
        can_add_player(), provided as its own named method purely for
        call-site readability (`if room.is_full(): ...` reads more
        clearly than `if not room.can_add_player(): ...` at some call
        sites, exactly like MatchmakingQueue's own find_match()/remove()
        pair each existing as their own clearly-named method rather
        than forcing every caller to spell out the underlying logic
        itself)."""

        return not self.can_add_player()

    def add_player(self, identity: object) -> None:
        """Add a real player (a GUEST) to this room.

        Args:
            identity: Any value identifying the new player - same
                agnostic-identity convention as `host_identity` above.

        Returns:
            None.

        Raises:
            RoomFullError: If a host and a guest already both occupy
                the room (see module docstring's "CAPACITY IS ENFORCED
                ONLY FOR PLAYERS" section for why this raises, rather
                than silently no-op-ing or overwriting the existing
                guest) - a caller is expected to check can_add_player()
                (or catch this) before calling this method.
        """

        if not self.can_add_player():
            raise RoomFullError(f"room {self.code!r} already has a host and a guest")

        self._members.append(RoomMember(identity=identity, role=Role.GUEST))

    def add_viewer(self, identity: object) -> None:
        """Add a viewer to this room - unconditionally, with no
        capacity check of any kind (see module docstring's "CAPACITY IS
        ENFORCED ONLY FOR PLAYERS" section: there is no real-world
        upper bound on how many people may watch a game, and no method
        in this class ever assumes one).

        Args:
            identity: Any value identifying the new viewer - same
                agnostic-identity convention as `host_identity` above.

        Returns:
            None.
        """

        self._members.append(RoomMember(identity=identity, role=Role.VIEWER))
