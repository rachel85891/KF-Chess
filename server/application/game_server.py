"""GameServer: the real protocol coordinator - Stage B3 of the server
track. This is the ONE component allowed to know about BOTH networking
(ConnectionManager, real ServerConnection objects) AND game hosting
(GameSession), exactly mirroring how
kungfu_chess/client/loop/game_loop.py's GameLoopRunner is the one
client-side class allowed to know about every client-layer piece at
once. Every other server/ module stays strictly single-purpose:
ConnectionManager (Stage B1) still only tracks connections and knows
nothing about chess; GameSession (Stage B2) still only hosts a headless
engine and knows nothing about networking; MatchmakingQueue (Stage E1)
still only matches waiting entries and knows nothing about networking
or GameSession either. This class is where all of those things
actually meet, and it is the only place they do.

THE APPLICATION/PRESENTATION BOUNDARY (refactor/server-application-
presentation-split): this file used to ALSO own every detail of how
the wire protocol is actually spoken - parsing raw text, formatting
every outgoing message, the literal connection.send calls - alongside
its own coordination decisions, in one 664-line file. That PRESENTATION
half is now server/presentation/protocol_handler.py's ProtocolHandler
(see its own module docstring for the full reasoning) - a stateless,
ConnectionManager/GameSession/EventBus-agnostic class this one holds
via composition (`self._protocol`, injected DIP, defaulting to a real
ProtocolHandler). This class (APPLICATION) keeps every decision about
what a client message MEANS for the game and who is allowed to send
it. Neither class reaches into the other's internals.

STAGE E1 - REAL MATCHMAKING REPLACES THE OLD FIXED-SINGLE-GAME MODEL
(feature/matchmaking-elo-queue-e1, CTD26 slides' own "Play button -
search for an opponent within ELO±100, one-minute timeout" framing):
every earlier stage (through Stage D2) constructed exactly ONE
GameSession, once, for the server's whole lifetime - the first two
authenticated connections were simply IT, color decided purely by
"1st=White, 2nd=Black" connection order. This stage removes that model
entirely. After a connection successfully authenticates, it no longer
joins a fixed session at all - it enters a REAL waiting pool
(server/application/matchmaking_queue.py's MatchmakingQueue, Stage E1's
own standalone, already-tested-in-isolation module) until the server
finds it a rating-compatible opponent (within 100 points, inclusive -
MatchmakingQueue's own documented pairing strategy) or 60 real seconds
pass with no match, whichever comes first.

WHY "server_full" (THE OLD THIRD-PLUS-CONNECTION POLICY) IS REMOVED
ENTIRELY, NOT KEPT ALONGSIDE MATCHMAKING (a real, consequential
decision, flagged here explicitly - not a silent scope-creep): the old
policy hard-capped the server at exactly two total connections, ever -
fundamentally incompatible with a matchmaking QUEUE, whose entire point
is that more than two people can be waiting/playing at once (otherwise
"search for an opponent within a rating range" is meaningless - there
would never be more than one possible opponent to search among). This
stage does not introduce any REPLACEMENT capacity cap of its own
either (the task names no such requirement) - any number of
authenticated connections may now wait or play concurrently. Every
pre-existing test asserting the OLD "third connection gets server_full"
scenario no longer has a scenario to test at all (a third connection
now simply joins the queue like any other) - see this stage's own git
history for exactly which pre-existing tests were removed/rewritten as
a direct, necessary consequence, mirroring Stage D2's own established
precedent of flagging every such change rather than asking to silently
preserve it.

REGISTRY OF ACTIVE MATCHES, KEYED BY MATCH ID - THE MINIMUM SHAPE THIS
STAGE NEEDS, NOT FULL ROOM ROUTING (per this stage's own explicit
scope boundary): `self._matches: Dict[int, _Match]`, where `_Match`
(below) bundles exactly what one real, in-progress game needs - its
own GameSession, and a `colors: Dict[ServerConnection, Color]` for
exactly its own two (or, after one disconnects, one) players. A
SEPARATE, future Rooms stage could grow `match_id` into a real,
client-visible room identifier and add room-scoped spectator/routing
features on top of this - nothing here forecloses that - but this
stage builds only what pairing two matched players together already
requires: a dynamically-constructed GameSession per pair (GameSession's
own constructor, completely unmodified, called once per match - that
class's own docstring already documented "a future multi-game/
multi-room stage can construct more than one GameSession without this
class changing at all", and this stage is the first to actually do so),
its own event-bus subscription (so broadcasts reach only ITS OWN two
connections, not every connection on the server), and its own entry in
the tick loop (see "TICK LOOP NOW ITERATES EVERY ACTIVE MATCH" below).

COLOR ASSIGNMENT FOR A MATCHED PAIR - QUEUE-JOIN ORDER, NOT RAW
CONNECTION ORDER (per this stage's own explicit requirement):
MatchmakingQueue.find_match() already returns its pair as
`(earlier_joined, later_joined)` (see that module's own "PAIRING
STRATEGY" docstring section) - `_create_match`, below, assigns White to
whichever entry joined the QUEUE earlier and Black to the other,
regardless of which one's underlying TCP connection was accepted
first. These can now genuinely differ: a connection that arrived
FIRST but has an incompatible rating for a long time could still be
waiting when a LATER-arriving, rating-compatible pair of others forms
and matches ahead of it - "first to actually get matched into White"
is therefore a property of the QUEUE, not the raw socket-accept
timeline, exactly as this stage's own task explicitly requires ("do
not reuse 'connection order' from the old model verbatim").

WHY THE OLD `self._join_lock` (Stage D2's own fix for a real, found
race) IS REMOVED, NOT CARRIED FORWARD: that lock existed because
Stage D2 introduced a real `await` gap between a connection being
accepted and its own color being decided (authentication takes real
time), which could reorder two connections' own color assignment
relative to their real arrival order without a lock serializing that
window. Color assignment no longer happens anywhere near connection-
accept time at all in this stage - it happens later, inside
`_create_match`, driven entirely by MatchmakingQueue's own
insertion-ordered internal dict, which is only ever mutated by plain,
synchronous, non-`await`-ing code (`add_waiting_player`/`find_match`/
`remove` - re-verified directly, none of MatchmakingQueue's own methods
contain an `await`). Under asyncio's single-threaded cooperative
scheduling, a synchronous code path with no internal `await` cannot be
interleaved by another coroutine's own code, so calling
`add_waiting_player` then `_attempt_matchmaking` back-to-back is
already atomic without a lock, for the identical reason color
assignment needed NO lock before Stage D2 ever existed. (Real
authentication STILL has its own genuine `await` gap, unchanged from
Stage D2 - but nothing consumes ITS OWN completion order for anything
order-sensitive anymore either: whichever connection's authentication
happens to finish first simply calls `add_waiting_player` first,
which - correctly, per the "COLOR ASSIGNMENT" section above - IS the
queue order this stage wants to use.)

DISCONNECTION WHILE WAITING (this stage's own explicit requirement 5):
`_wait_for_match`, below, races the real match-completion future
against a real `connection.recv()` call using `asyncio.wait(...,
return_when=asyncio.FIRST_COMPLETED)` - if the client disconnects (or,
in principle, sends something unexpected) while still queued, the
`recv()` half completes first (with a ConnectionClosed exception
stored on that task, or an unexpected message), and this method removes
the entry from the matchmaking queue and returns None cleanly - no
crash, no entry left lingering in the queue to be matched against a
connection that no longer exists.

TIMEOUT MECHANISM - REUSES THE EXISTING TICK LOOP, NOT A SEPARATE
TIMER TASK (this stage's own "decide and justify" requirement):
`run_tick_loop` already runs forever, once, as the server's own
established "periodic background work" mechanism (TICK_INTERVAL_S,
~33ms) - `_check_matchmaking_timeouts` is called once per tick,
alongside advancing every active match's own GameSession. A dedicated,
separate timer task for a 60-second timeout would be introducing a
SECOND periodic-background-work mechanism for what is fundamentally
the same category of work the tick loop already exists to do; checking
every ~33ms is far finer-grained than a 60-second bound strictly needs,
but the check itself is a cheap, bounded dict scan over however many
entries are currently waiting, so the extra granularity costs nothing
meaningful. WHY "ON NEW ARRIVAL" ALONE ISN'T ENOUGH FOR THE TIMEOUT
(only for the MATCHING half): a lone waiting player with no compatible
opponent needs to be evicted after 60 real seconds even if NO new
connection ever arrives to trigger a fresh check - nothing about a NEW
arrival is required to detect "this OTHER, unrelated entry has now
waited too long." Matching itself, by contrast, genuinely only needs
an "on arrival" trigger (re-verified directly: removing entries, via
either a match or a timeout, can never CREATE a new valid pair among
the entries that remain - only adding a new entry can) - so this stage
does NOT also periodically retry `find_match()`, only the (separate,
time-based) timeout check.

TICK LOOP NOW ITERATES EVERY ACTIVE MATCH, NOT ONE FIXED SESSION:
`run_tick_loop`'s own body changes from a single `self._session.
wait(delta_ms)` call to `for match in list(self._matches.values()):
match.session.wait(delta_ms)` - a snapshot copy of `.values()`, not the
live dict, so a match finishing/being cleaned up mid-iteration
(e.g. both players having disconnected) can never raise "dictionary
changed size during iteration."

MATCH CLEANUP ON DISCONNECT: `handle_connection`'s own `finally` block
now pops only the departing connection's own entry from `match.colors`
(mirroring the OLD model's own identical `self._colors.pop(connection,
None)` - a single player disconnecting from an in-progress match was
never handled beyond this before this stage either, and this stage
does not build anything new for "opponent disconnects mid-game" beyond
what already existed, now correctly scoped per-match instead of
globally). If BOTH players of a match have now disconnected (`match.
colors` is empty), the whole match entry is also removed from
`self._matches` - a genuinely NEW cleanup this stage needs (unlike the
old single, permanent, server-lifetime session, a dynamically-created
match that nobody is left to play or watch would otherwise just sit in
`self._matches` ticking forever for no reason).

`session_factory` REPLACES THE OLD `session: Optional[GameSession]`
CONSTRUCTOR PARAMETER (a real, necessary, and flagged breaking change):
the old parameter injected one, ALREADY-BUILT GameSession instance,
because there was only ever one session to build, for the server's
whole lifetime. Now that a fresh GameSession is constructed dynamically
per match (`GameSession()`, its own constructor completely unmodified,
per this stage's own explicit requirement), a single pre-built instance
no longer makes sense to inject - `session_factory: Callable[[],
GameSession] = GameSession` is injected instead (defaulting to the real
GameSession class itself, callable with no arguments, exactly matching
its own real production usage) - a test that wants every dynamically-
created match to start from a CUSTOM board (e.g. a pre-arranged
capture, for score/log broadcast tests) injects
`session_factory=lambda: GameSession(board=Board(custom_grid))`
instead of a single pre-built session object.

STAGE D2 - REAL AUTH HANDSHAKE (feature/home-screen-d2-auth-protocol,
UNCHANGED by this stage - re-verified directly): `handle_connection`'s
own AUTH exchange (read the client's first message, parse it as
"AUTH:<username>:<password>", sign up or log in via UserRepository,
off the event loop thread via a persistent single-worker executor - see
"WHY UserRepository'S OWN SYNCHRONOUS CALLS ARE OFFLOADED..."/"LAZY,
THREAD-PINNED CONSTRUCTION" below) is completely untouched - this stage
only changes what happens AFTER a successful authentication (queue
instead of immediate fixed-session join).

WHY UserRepository'S OWN SYNCHRONOUS CALLS ARE OFFLOADED TO A SINGLE,
DEDICATED WORKER THREAD - NOT asyncio.to_thread's OWN DEFAULT EXECUTOR:
every one of GameServer's own async methods runs on asyncio's single
event-loop thread - a synchronous sqlite3 call (real disk I/O, or real
CPU-bound PBKDF2 hashing) executed directly on that thread would block
EVERY connection this server is juggling, including the tick loop, for
as long as that one call takes. `asyncio.to_thread` itself was tried
FIRST and rejected: its default executor draws from a pool of multiple,
not-guaranteed-identical worker threads across separate calls, but
sqlite3.Connection objects are bound FOREVER to whichever single OS
thread constructed them (UserRepository is off-limits to modify, so it
is never constructed with `check_same_thread=False`); any call from a
different thread raises `sqlite3.ProgrammingError` immediately. THE
FIX: `self._user_repository_executor`, a `concurrent.futures.
ThreadPoolExecutor(max_workers=1)` held for this instance's whole
lifetime - every UserRepository-touching call (including the
UserRepository object's own construction) is submitted to THIS one
persistent executor via `loop.run_in_executor(...)`, guaranteeing every
call runs on the literal same OS thread.

LAZY, THREAD-PINNED CONSTRUCTION: `self._user_repository` is
constructed LAZILY, the first time `_authenticate_sync` ever runs -
already executing ON the persistent worker thread at that point - not
eagerly in `__init__` (which runs on the event-loop thread, the wrong
one). This is why this class accepts `user_repository_db_path:
Optional[str]` (a real filesystem path, or ":memory:") rather than an
already-built UserRepository instance: an externally-constructed
instance's connection would already be bound to whichever thread built
it (almost always the event-loop thread), which can never match this
class's own persistent worker thread.

MOVE COMMAND REJECTION SCHEME (a plain-text response sent directly and
ONLY to the offending client - never broadcast, since these rejections
never reach a match's own GameSession/event bus at all): a single
"rejected:<reason>" prefix, with `<reason>` one of "malformed:<detail>"
/ "wrong_color" / "piece_mismatch" - see `_handle_move_command`/
`_handle_jump_command` below for the exact checks each one covers. A
move that gets this far and is still rejected by the real engine is NOT
covered by this scheme - GameEventPublisher already publishes a real
MoveRejected event for that case, turned into a normal board-state
broadcast to the match's own two connections by this class's own
broadcaster, the same as any other real game event.

JUMP COMMAND ROUTING AND REJECTION SCHEME: dispatched by
`_handle_message` based on a single leading-character check
(`message[:1].upper() == JUMP_COMMAND_PREFIX` means a jump command).
Jump rejection reuses the same three "rejected:<reason>" tokens as
moves, via a shared `_piece_matches` helper, plus one new token,
"jump_rejected", for the one case moves never needed a direct-response
token for (ExtraEngine.request_jump returns a bare bool with no reason
string when it declines).

WHY THE BROADCASTER BRIDGES A SYNC CALLBACK INTO AN ASYNC SEND:
kungfu_chess.bus.EventBus.subscribe requires a plain synchronous
callable, and GameSession.request_move/wait call the whole
GameEventPublisher._notify chain synchronously, inline, with no
`await` anywhere in that path - but actually delivering a broadcast
requires a real, awaited `connection.send(...)`. The bridge:
`_on_game_event` (the subscribed handler, now bound to its own match
via `functools.partial` at subscription time - see `_create_match`) is
itself a plain sync function that only schedules
`asyncio.create_task(self._broadcast_event(match, event))`, which does
the real, awaited sends.

TICK LOOP / TICK RATE: `run_tick_loop` mirrors GameLoopRunner.run()'s
own real-time delta measurement pattern - `time.perf_counter()`
before/after each real sleep, fed as delta_ms into every active
match's own `GameSession.wait(delta_ms)`. TICK_INTERVAL_S = 1/30
matches client_spec.md §8's own ~30 FPS default.

STAGE B7 / GameOver / SCORE-MOVE-LOG-TIMER BROADCAST (all UNCHANGED by
this stage, re-verified directly - only now scoped per-match instead of
globally): `_broadcast_event` sends the real, structured wire-format
event message (if any), THEN the board-text snapshot, THEN (for
MoveAccepted/JumpAccepted/PieceArrived only) the score/move-log/
elapsed-clock snapshot - to the match's own two connections only.

BUGFIX - INITIAL BOARD STATE ON JOIN (UNCHANGED IN SPIRIT, now sent
once a match actually exists rather than once a fixed session exists):
a freshly-matched connection receives the current board state as a
direct, point-to-point send immediately after its own assigned_color
message - the same fix from an earlier stage, now naturally happening
once matchmaking (rather than raw connection) completes.

STAGE E2 - DISCONNECT COUNTDOWN / AUTO-RESIGN (feature/disconnect-
countdown-autoresign-e2, CTD26 slides' own "auto-resign after 20
seconds of disconnection, with a visible countdown" framing): before
this stage, a real ConnectionClosed during an ACTIVE match's own
`async for message in connection` loop (the try/except this class has
always had) simply popped that connection out of `match.colors` and
moved on - the opponent was never told anything, and the game itself
never actually ended even though one side was gone forever. This stage
gives a disconnecting player a real, visible 20-second grace window
before the match is auto-resigned in their opponent's favor, with
narrow, scoped support for the SAME username reconnecting during that
window to resume play.

SCOPE BOUNDARY, RESTATED EXPLICITLY (per this stage's own task): this
is NOT general reconnect/resume support - it is narrowly "the exact
same username, re-authenticating while a countdown for a match they
were just disconnected from is still running, gets put back into that
SAME GameSession/color." A username that never had a countdown running
(or whose countdown already expired) goes through the ordinary
matchmaking queue exactly as before, unaffected. Full reconnect/resume
(e.g. rejoining a match after a server restart, resuming after the
countdown expired, spectating) remains an explicitly out-of-scope,
accepted gap - GameSession itself never stopped running during a
countdown (only the WebSocket needed swapping back in), which is the
one narrow property this whole mechanism depends on and the reason a
countdown-window reconnect is tractable at all while general resume
still is not.

WHY DISCONNECT-COUNTDOWN STATE IS TRACKED BY USERNAME, NOT BY
CONNECTION OBJECT (a real, necessary design decision this stage's own
task explicitly calls out): `match.colors` itself is still keyed by
`ServerConnection` (unchanged - see "REGISTRY OF ACTIVE MATCHES" above)
because that mapping only ever needs to answer "which color does THIS
socket, right now, speak for" - which is exactly connection-object-
shaped. A disconnect countdown's whole POINT, however, is that the
original connection OBJECT is gone forever the instant its socket
closes (websockets never hands back a closed ClientConnection/
ServerConnection to reconnect on top of) - there is nothing left to key
new state on except the one thing that outlives the dead socket and
uniquely identifies "the same player": their authenticated username. A
brand new `self._pending_disconnects: Dict[str, _PendingDisconnect]`
(new, this stage) therefore tracks "this username's own match/color
slot is currently up for grabs" independently of any connection object
- `_PendingDisconnect` (new dataclass, below) bundles the real `_Match`,
the disconnected `Color`, the username (for symmetry/logging - also the
dict key itself), `disconnected_at` (this instance's own `self._clock()`
value at detection time, mirroring `WaitingPlayer.joined_at`'s own
injectable-clock convention from Stage E1), and a real
`asyncio.Future[bool]` (`resolution`) that gets resolved exactly once,
by whichever of two independent code paths gets there first: a
reconnecting connection (`True`) or the tick loop's own expiry check
(`False`) - mirroring `_waiting_futures`'s own identical "resolved by
whichever of two independent paths reaches it first" shape from Stage
E1's own matchmaking wait, reused here for a structurally analogous
problem rather than inventing a different synchronization primitive.

THE DISCONNECTING CONNECTION'S OWN COROUTINE LINGERS UNTIL THE
COUNTDOWN RESOLVES (`_handle_active_match_disconnect`, new): once
`ConnectionClosed` ends the `async for message in connection` loop,
`handle_connection` no longer falls straight to cleanup - it registers
a `_PendingDisconnect`, notifies the opponent (see "WIRE MESSAGE" below),
and `await`s that same `resolution` future with NO timeout of its own.
This exactly mirrors Stage E1's own `_wait_for_match`'s shape (wait on a
future that some OTHER code path resolves) rather than inventing a
second synchronization idiom, and it is what makes this stage's own
20-second wait reuse the EXISTING tick loop rather than a dedicated
timer task (see "TIMEOUT MECHANISM REUSES THE TICK LOOP" below): the
future is only ever resolved externally, never by this coroutine
itself polling anything.

WIRE MESSAGE - SENT ONCE, NOT ON A PERIODIC TIMER (this stage's own
"decide and justify" requirement): `format_opponent_disconnected(
disconnect_countdown_s)` ("opponent_disconnected:20" -
server/presentation/protocol_handler.py's own new docstring section)
is sent to the still-connected opponent exactly once, at the moment
the disconnect is first detected - never repeated on a countdown-
ticking timer. The client renders its own local countdown from that
one authoritative value, using its own wall clock, exactly mirroring
Stage B7.5's own established "client-local timing between authoritative
updates" pattern (a pixel slide's progress, and the elapsed-game-clock
display, are both already computed this way - see
kungfu_chess/client/loop/network_game_loop_runner.py's own docstring
for both) - the same principle applies here without modification: two
real-time clocks (this server's own tick loop, and the client's own
render loop) both advance at real wall-clock speed, so a client-side
countdown computed from "seconds since I received this one message"
stays visually correct with no server-side ticking needed, and a real,
later "opponent_reconnected"/GameOver message is itself the correction
if anything ever drifted. Sending a message every tick instead would
mean 30 messages/second of pure countdown-ticking noise for no
observable benefit over one message plus client-side interpolation.

TIMEOUT MECHANISM REUSES THE TICK LOOP, NOT A SEPARATE TIMER TASK
(mirrors Stage E1's own identical "decide and justify" reasoning
verbatim - see that stage's own "TIMEOUT MECHANISM" docstring section
above): `_check_disconnect_countdowns`, new, is called once per tick
alongside the pre-existing `_check_matchmaking_timeouts` - a dedicated,
separate timer task for this 20-second window would be a SECOND
periodic-background-work mechanism for the same category of work the
tick loop already exists to do, for the exact same reasoning Stage E1
already rejected that approach for its own 60-second window.

RESIGN REUSES THE EXISTING GameOver MECHANISM VERBATIM, NOT A SECOND,
PARALLEL GAME-ENDING PATH (this stage's own explicit requirement):
`_check_disconnect_countdowns`, on a real expiry with no reconnect,
calls `pending.match.session.resign(loser_color=pending.color)` -
server/application/game_session.py's own new, narrow method (see that
class's own "STAGE E2" docstring section for exactly why it lives
there and exactly what it does: set the SAME `engine.state.game_over`
flag a real king-capture GameOver already sets, and publish the SAME
real `GameOver` event through the SAME `event_bus` every other real
game event already flows through). This class's own EXISTING
`_on_game_event`/`_broadcast_event` machinery (subscribed once per
match in `_create_match`, completely untouched by this stage) then
picks up and broadcasts that GameOver to this match's own connections
with ZERO changes needed here - the still-connected opponent's own
client displays it via the EXACT SAME GameOverOverlayRenderer/freeze-
and-display UX a real king-capture-ended game already uses (see
kungfu_chess/client/loop/network_game_loop_runner.py's own "GAME OVER
OVER THE NETWORK" docstring section, unchanged by this stage), not a
second, differently-worded "resignation" message.

RECONNECT: HOW A NEW CONNECTION OBJECT RESUMES AN EXISTING MATCH/COLOR
SLOT (`_resume_if_pending_disconnect`, new, called from
`handle_connection` immediately after a successful AUTH, BEFORE the
existing matchmaking-queue path): looks up
`self._pending_disconnects` by the JUST-AUTHENTICATED username (the
one stable identity that survived the old connection's own death - see
"WHY... TRACKED BY USERNAME" above). If found (and not already resolved
- see "A REAL, NARROW RACE" below), this is a resume, not a fresh
join: `match.colors[connection] = pending.color` re-associates the
BRAND NEW connection object with the SAME color in the SAME, still-
running `_Match` (the old, dead connection object's own entry is left
alone here - the OLD connection's own lingering `_handle_active_match_
disconnect` coroutine pops it, once its own `await resolution` returns,
exactly mirroring how any other disconnecting connection's own cleanup
already works), `pending.resolution.set_result(True)` releases that
lingering old coroutine, the opponent is sent
`format_opponent_reconnected()`, and the resumed connection receives
the EXACT SAME two-message join sequence a fresh match would
(assigned_color+rating, then the current board text) - genuinely the
SAME GameSession, mid-game, never restarted - before this method
returns and `handle_connection` proceeds into the SAME `async for
message in connection` loop as any other already-matched connection,
with no special-cased code path there at all. If NOT found (the common
case - a fresh login, or a username whose countdown already expired),
this method returns None and `handle_connection` falls through to the
existing, completely unmodified SEARCHING_FOR_OPPONENT_MESSAGE +
`_wait_for_match` sequence.

A REAL, NARROW RACE THIS STAGE GUARDS AGAINST (`pending.resolution.
done()` checked before honoring a resume): it is possible, in
principle, for a reconnect attempt and the tick loop's own expiry
check to both be "in flight" at nearly the same real moment. Because
`_check_disconnect_countdowns` always POPS an expiring entry from
`self._pending_disconnects` before resolving its own future (and
because both this method and that one run on the SAME single-threaded
event loop, so neither can preempt the other mid-statement), only ONE
of the two can ever actually WIN this race in practice - but the
`.done()` check is kept anyway as a cheap, explicit invariant (mirrors
`_check_matchmaking_timeouts`'s own identical `if future is not None
and not future.done()` defensive check from Stage E1) rather than
relying purely on dict-pop ordering to make it merely appear
impossible. A reconnect that loses this race (vanishingly rare) simply
falls through to ordinary matchmaking instead, exactly like any other
username with no pending countdown.

A DOUBLE-DISCONNECT RACE (BOTH PLAYERS OF THE SAME MATCH DISCONNECT
INDEPENDENTLY) IS HANDLED BY GameSession.resign's OWN GUARD, NOT HERE:
see that method's own "GUARDED AGAINST A DOUBLE-RESIGN RACE" docstring
section - `_check_disconnect_countdowns` does not need its own separate
guard for this, since resign() itself already refuses to overwrite an
already-decided winner.

STAGE D3 - ELO RATING UPDATE ON REAL GAMEOVER (feature/elo-rating-
update-d3): server/persistence/user_repository.py's own `update_rating`
was built (Stage D1) but never called by anything - this stage finally
calls it, computing a real ELO update (server/application/
elo_rating.py, Stage D3's own new, pure computation module) for BOTH
players the moment a real GameOver actually happens, regardless of
which of this project's THREE real causes produced it (an ordinary
arrival-based king capture, a jump-interception king capture, or Stage
E2's own auto-resign-on-disconnect-timeout).

THE SINGLE RIGHT CHOKE POINT - `_broadcast_event`, NOT EACH OF THE
THREE TRIGGER SITES (this stage's own explicit "find the single right
choke point" requirement): all three causes already converge on
EXACTLY ONE piece of code before this stage ever existed - a real
`GameOver` instance published onto a match's own `session.event_bus`
(king capture/interception via `GameEventPublisher.wait`'s own
`pending.append(GameOver(...))` calls; resignation via
`GameSession.resign`'s own direct `self.event_bus.publish(GameOver(...))`
- see that method's own "STAGE E2" docstring section) - which this
class already subscribes to, once per match, in `_create_match`, and
already reacts to in `_broadcast_event` via `_on_game_event`. Adding
`if isinstance(event, GameOver): await self._apply_and_notify_rating_
update(match, event)` to that ONE existing method (rather than
separately calling something equivalent inside GameEngine.wait/
ExtraEngine.wait/GameSession.resign, all three of which requirement 4
explicitly forbids modifying anyway) is therefore not merely
convenient but the ONLY place this can be added exactly once - by
construction, `_broadcast_event` already runs EXACTLY once per real
GameOver (the SAME `engine.state.game_over` guard that prevents a
second king capture or a second resign() from ever publishing a SECOND
GameOver at all - see GameSession.resign's own "GUARDED AGAINST A
DOUBLE-RESIGN RACE" section - means this class can never be asked to
apply a rating update twice for the same match either).

`_Match` GAINS `usernames: Dict[Color, str]` (a real, necessary,
narrowly-scoped addition - NOT a change to any of the three GameOver-
triggering mechanisms): computing an ELO update needs BOTH players'
CURRENT ratings, looked up via `UserRepository.get_rating(username)` -
but `_Match.colors` only ever mapped `ServerConnection -> Color`, never
username at all (a connection object carries no username of its own).
Keyed by `Color`, not by `ServerConnection`, deliberately: a color's
own identity is stable for a match's whole real lifetime, but its
CONNECTION OBJECT is not (Stage E2's own reconnect-resume can swap in a
brand new connection object for the SAME color mid-match) - `usernames`
therefore survives a reconnect with zero additional bookkeeping,
populated exactly once, in `_create_match`, straight from the two real
`WaitingPlayer.username` fields `_create_match` already receives (no
new lookup of any kind - the data was already sitting right there,
simply never threaded through to `_Match` before this stage needed it).

`_apply_and_notify_rating_update`: resolves `winner_username`/
`loser_username` from `match.usernames` via `event.winner_color`/its
own `.opposite`, then does the real UserRepository work (get both old
ratings, compute both new ones via `elo_rating.compute_new_ratings`,
persist both) via `loop.run_in_executor(self._user_repository_executor,
...)` - the EXACT SAME persistent, single worker thread `_authenticate`
already uses (see this class's own "WHY UserRepository'S OWN
SYNCHRONOUS CALLS ARE OFFLOADED..." section above - sqlite3's own
thread-affinity constraint applies identically here, and reusing the
SAME already-built executor, rather than a second one, is what
guarantees every UserRepository call this whole class ever makes still
runs on the literal same OS thread). `self._user_repository` is
guaranteed already constructed by the time any match exists (every
player must have authenticated - and therefore already called
`_authenticate_sync`, which lazily builds it - before ever being
matched at all), so no additional lazy-construction guard is needed
here beyond what `_authenticate_sync` already provides.

WIRE MESSAGE SENT POINT-TO-POINT, PER CONNECTION CURRENTLY IN
`match.colors` (see server/presentation/protocol_handler.py's own
"STAGE D3" docstring section for why this is its own separate message,
never a field merged into the shared "EVT:GAMEOVER:..." broadcast):
`format_rating_update(old_rating, new_rating)` is sent individually to
each `(connection, color)` still present in `match.colors` at the
moment the update is applied, using THAT color's own old/new pair -
correctly reaches a Stage-E2-resumed connection automatically (it's
just whatever connection object currently occupies that color's own
slot, read fresh via `match.colors.items()`), and correctly, safely
no-ops for a color whose connection already disconnected (e.g. the
auto-resigned loser's own dead connection, still present in
`match.colors` at this exact moment - see Stage E2's own "MATCH CLEANUP
ON DISCONNECT" section for why - `ProtocolHandler.send`'s own existing
ConnectionClosed-swallowing policy already covers this, unchanged).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import functools
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Tuple

from websockets.asyncio.server import ServerConnection
from websockets.exceptions import ConnectionClosed

from kungfu_chess.client.events.game_events import (
    AttackerIntercepted,
    GameOver,
    JumpAccepted,
    JumpLanded,
    MoveAccepted,
    MoveRejected,
    PieceArrived,
)
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.notation.jump_command import MalformedJumpCommandError, ParsedJumpCommand
from server.application.elo_rating import compute_new_ratings
from server.application.game_session import GameSession
from server.application.matchmaking_queue import MatchmakingQueue, WaitingPlayer
from server.persistence.user_repository import UserRepository
from server.presentation.auth_command import MalformedAuthCommandError
from server.presentation.connection_manager import ConnectionManager
from server.presentation.move_command import MalformedCommandError, ParsedMoveCommand
from server.presentation.protocol_handler import SEARCHING_FOR_OPPONENT_MESSAGE, ProtocolHandler

TICK_INTERVAL_S = 1 / 30
DEFAULT_MATCHMAKING_TIMEOUT_S = 60.0
DEFAULT_DISCONNECT_COUNTDOWN_S = 20.0

_BROADCAST_EVENT_TYPES = (
    MoveAccepted,
    JumpAccepted,
    JumpLanded,
    AttackerIntercepted,
    MoveRejected,
    PieceArrived,
    GameOver,
)


@dataclass
class _Match:
    """One dynamically-created, real game between exactly two matched
    players - see module docstring's "REGISTRY OF ACTIVE MATCHES"
    section for the full reasoning."""

    match_id: int
    session: GameSession
    colors: Dict[ServerConnection, Color] = field(default_factory=dict)
    # Stage D3 - see module docstring's "STAGE D3" section for why this
    # is keyed by Color (survives a Stage-E2 reconnect unchanged),
    # populated once, in _create_match, from the two WaitingPlayer.
    # username fields already available there.
    usernames: Dict[Color, str] = field(default_factory=dict)


@dataclass
class _PendingDisconnect:
    """One username's own real, in-progress disconnect countdown - see
    module docstring's "WHY DISCONNECT-COUNTDOWN STATE IS TRACKED BY
    USERNAME, NOT BY CONNECTION OBJECT" section for the full reasoning
    behind every field below."""

    match: _Match
    color: Color
    username: str
    disconnected_at: float
    resolution: "asyncio.Future[bool]"


class GameServer:
    """The APPLICATION half of the server track's APPLICATION/
    PRESENTATION split - see module docstring for the full reasoning
    behind every decision below, including this stage's own sweeping
    "fixed single game" -> "real matchmaking" architectural shift."""

    def __init__(
        self,
        connection_manager: Optional[ConnectionManager] = None,
        protocol_handler: Optional[ProtocolHandler] = None,
        user_repository_db_path: Optional[str] = None,
        matchmaking_queue: Optional[MatchmakingQueue] = None,
        session_factory: Callable[[], GameSession] = GameSession,
        matchmaking_timeout_s: float = DEFAULT_MATCHMAKING_TIMEOUT_S,
        disconnect_countdown_s: float = DEFAULT_DISCONNECT_COUNTDOWN_S,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        """Construct (or accept injected) collaborators - see module
        docstring for the full reasoning behind every parameter below.

        Args:
            connection_manager: The ConnectionManager to coordinate.
                Defaults to a fresh, real, empty ConnectionManager -
                injectable for tests.
            protocol_handler: The ProtocolHandler this instance
                delegates every wire-parsing/formatting/send concern
                to. Defaults to a fresh, real, stateless ProtocolHandler
                - injectable (DIP) for tests.
            user_repository_db_path: The real filesystem path (or
                ":memory:") the real, lazily-constructed UserRepository
                is built with - see module docstring's "LAZY,
                THREAD-PINNED CONSTRUCTION" section for why this is a
                path, not an already-built instance. Defaults to None,
                which uses UserRepository's own real default path.
            matchmaking_queue: The MatchmakingQueue to coordinate.
                Defaults to a fresh, real MatchmakingQueue constructed
                with this instance's own `clock` - injectable for tests
                that want to control the queue directly.
            session_factory: A zero-argument callable constructing a
                fresh GameSession for each new match - see module
                docstring's "`session_factory` REPLACES..." section for
                why this replaced the old single, pre-built `session`
                parameter. Defaults to the real GameSession class
                itself.
            matchmaking_timeout_s: How long (real seconds) a connection
                may wait in the matchmaking queue before being timed
                out - see module docstring's "TIMEOUT MECHANISM"
                section. Defaults to 60 (this stage's own "one-minute
                timeout" requirement) - overridable for tests, so no
                test needs a real 60-second wait.
            disconnect_countdown_s: How long (real seconds) a
                connection that disconnects during an ACTIVE match may
                remain reconnectable (under the SAME username) before
                that match is auto-resigned in the opponent's favor -
                see module docstring's "STAGE E2" section. Defaults to
                20 (this stage's own "auto-resign after 20 seconds"
                requirement) - overridable for tests, so no test needs
                a real 20-second wait.
            clock: Callable returning the current time as a float -
                defaults to time.perf_counter. Used both to construct
                the default MatchmakingQueue and for this instance's
                own periodic timeout checks, so all three stay
                consistent.

        Returns:
            None.
        """

        self._connection_manager = connection_manager if connection_manager is not None else ConnectionManager()
        self._protocol = protocol_handler if protocol_handler is not None else ProtocolHandler()
        self._user_repository_db_path = user_repository_db_path
        self._user_repository: Optional[UserRepository] = None
        # See module docstring's "WHY UserRepository'S OWN SYNCHRONOUS
        # CALLS ARE OFFLOADED..." section - exactly one worker thread,
        # reused for every UserRepository-touching call (including its
        # own lazy construction) for this instance's whole lifetime, so
        # sqlite3's own check_same_thread constraint is never violated.
        self._user_repository_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        self._clock = clock
        self._session_factory = session_factory
        self._matchmaking_timeout_s = matchmaking_timeout_s
        self._disconnect_countdown_s = disconnect_countdown_s
        self._matchmaking_queue = (
            matchmaking_queue if matchmaking_queue is not None else MatchmakingQueue(clock=self._clock)
        )

        self._matches: Dict[int, _Match] = {}
        self._next_match_id = 1
        # Populated in _wait_for_match, resolved either by _create_match
        # (with the real _Match) or _check_matchmaking_timeouts (with
        # None) - see module docstring's "TIMEOUT MECHANISM" and
        # "DISCONNECTION WHILE WAITING" sections.
        self._waiting_futures: Dict[ServerConnection, "asyncio.Future[Optional[_Match]]"] = {}

        # Stage E2 - keyed by USERNAME, not connection object - see
        # module docstring's "WHY DISCONNECT-COUNTDOWN STATE IS TRACKED
        # BY USERNAME..." section for the full reasoning.
        self._pending_disconnects: Dict[str, _PendingDisconnect] = {}

    async def handle_connection(self, connection: ServerConnection) -> None:
        """websockets.serve's own per-connection handler - authenticates
        the connection (Stage D2, unchanged), then enters the real
        matchmaking queue (Stage E1) until matched or timed out, then
        reads move commands from this connection until it disconnects.

        Args:
            connection: The real ServerConnection websockets.serve
                handed this coroutine for one accepted client.

        Returns:
            None.
        """

        try:
            raw_auth_message = await connection.recv()
        except ConnectionClosed:
            # The client disconnected before ever sending its own AUTH
            # command - nothing was ever tracked for it.
            return

        try:
            parsed_auth = self._protocol.parse_incoming_auth_command(raw_auth_message)
        except MalformedAuthCommandError as exc:
            await self._protocol.send(connection, self._protocol.format_rejection(f"malformed:{exc}"))
            await connection.close()
            return

        rating = await self._authenticate(parsed_auth.username, parsed_auth.password)
        if rating is None:
            await self._protocol.send(connection, self._protocol.format_rejection("wrong_password"))
            await connection.close()
            return

        self._connection_manager.add(connection)

        resumed = await self._resume_if_pending_disconnect(connection, parsed_auth.username, rating)
        if resumed is not None:
            match, color = resumed
        else:
            await self._protocol.send(connection, SEARCHING_FOR_OPPONENT_MESSAGE)

            match = await self._wait_for_match(connection, parsed_auth.username, rating)
            if match is None:
                # Timed out (the periodic check already sent the
                # timeout message and closed the connection) or
                # disconnected while still queued (nothing left to send
                # at all) - either way, nothing further to do here.
                self._connection_manager.remove(connection)
                return

            color = match.colors[connection]
            await self._protocol.send(connection, self._protocol.format_assigned_color(color, rating))
            await self._protocol.send(connection, self._current_board_text(match))

        try:
            async for message in connection:
                await self._handle_message(match, connection, color, message)
        except ConnectionClosed:
            pass

        # Stage E2 - a disconnect during an ACTIVE match no longer falls
        # straight to cleanup: see module docstring's "STAGE E2" section
        # and _handle_active_match_disconnect's own docstring for the
        # full reasoning (a real, visible countdown, with narrow,
        # scoped support for the SAME username reconnecting during it).
        # This does NOT affect a disconnect while merely WAITING in the
        # matchmaking queue at all - that path is entirely separate,
        # inside _wait_for_match, above, unchanged by this stage.
        await self._handle_active_match_disconnect(match, connection, color, parsed_auth.username)
        self._connection_manager.remove(connection)

    async def _wait_for_match(
        self, connection: ServerConnection, username: str, rating: int
    ) -> Optional[_Match]:
        """Enter the matchmaking queue and wait for either a real
        match or this connection disconnecting/sending something
        unexpected while still queued - see module docstring's
        "DISCONNECTION WHILE WAITING" section for the full reasoning.

        Args:
            connection: The authenticated connection now entering the
                queue.
            username: This connection's own username.
            rating: This connection's own current rating.

        Returns:
            The real _Match this connection was paired into, or None
            if it timed out or disconnected before ever being matched.
        """

        loop = asyncio.get_running_loop()
        match_future: "asyncio.Future[Optional[_Match]]" = loop.create_future()
        self._waiting_futures[connection] = match_future

        # See module docstring's "WHY THE OLD self._join_lock... IS
        # REMOVED" section - both calls below are plain, synchronous,
        # non-`await`-ing code, already atomic under asyncio's
        # cooperative scheduling with no lock needed.
        self._matchmaking_queue.add_waiting_player(connection, username, rating)
        self._attempt_matchmaking()

        recv_task = asyncio.ensure_future(connection.recv())
        match_task = asyncio.ensure_future(match_future)
        done, _pending = await asyncio.wait({recv_task, match_task}, return_when=asyncio.FIRST_COMPLETED)
        self._waiting_futures.pop(connection, None)

        if match_task in done:
            recv_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, ConnectionClosed):
                await recv_task
            return match_task.result()

        # recv_task completed first - the client disconnected, or sent
        # something unexpected, while still waiting in queue.
        match_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await match_task
        self._matchmaking_queue.remove(connection)
        with contextlib.suppress(ConnectionClosed):
            recv_task.result()
        return None

    def _attempt_matchmaking(self) -> None:
        """Consume every valid pair currently available in the
        matchmaking queue, creating a real match for each - see module
        docstring's "REGISTRY OF ACTIVE MATCHES" section. Loops (not
        just one match per call) so a single new arrival can unlock
        more than one simultaneous match if the queue backlog allows
        it."""

        while True:
            pair = self._matchmaking_queue.find_match()
            if pair is None:
                return
            first, second = pair
            self._matchmaking_queue.remove(first.connection_id)
            self._matchmaking_queue.remove(second.connection_id)
            self._create_match(first, second)

    def _create_match(self, first: WaitingPlayer, second: WaitingPlayer) -> None:
        """Construct a real, fresh GameSession for exactly this pair,
        assign colors by queue-join order (see module docstring's
        "COLOR ASSIGNMENT FOR A MATCHED PAIR" section), subscribe this
        match's own broadcaster, and wake up both connections' own
        handle_connection coroutines with the result.

        Args:
            first: The earlier-joined of the matched pair - becomes
                White.
            second: The later-joined of the matched pair - becomes
                Black.

        Returns:
            None.
        """

        match_id = self._next_match_id
        self._next_match_id += 1
        session = self._session_factory()
        colors: Dict[ServerConnection, Color] = {first.connection_id: Color.WHITE, second.connection_id: Color.BLACK}
        usernames: Dict[Color, str] = {Color.WHITE: first.username, Color.BLACK: second.username}
        match = _Match(match_id=match_id, session=session, colors=colors, usernames=usernames)
        self._matches[match_id] = match

        for event_type in _BROADCAST_EVENT_TYPES:
            session.event_bus.subscribe(event_type, functools.partial(self._on_game_event, match))

        for entry in (first, second):
            future = self._waiting_futures.get(entry.connection_id)
            if future is not None and not future.done():
                future.set_result(match)

    async def _check_matchmaking_timeouts(self) -> None:
        """Evict every waiting entry that has been queued longer than
        this instance's own `matchmaking_timeout_s` - see module
        docstring's "TIMEOUT MECHANISM" section for why this is called
        once per tick-loop iteration rather than via a separate timer
        task.

        Returns:
            None.
        """

        now = self._clock()
        expired = self._matchmaking_queue.expire_timed_out(now, self._matchmaking_timeout_s)
        for entry in expired:
            connection = entry.connection_id
            await self._protocol.send(connection, self._protocol.format_matchmaking_timeout(self._matchmaking_timeout_s))
            await connection.close()
            future = self._waiting_futures.get(connection)
            if future is not None and not future.done():
                future.set_result(None)

    async def _resume_if_pending_disconnect(
        self, connection: ServerConnection, username: str, rating: int
    ) -> Optional[Tuple[_Match, Color]]:
        """If `username` has a real disconnect countdown currently
        running (see module docstring's "STAGE E2" section), resume
        this BRAND NEW connection into that SAME match/color and cancel
        the countdown - otherwise, return None so the caller falls
        through to ordinary matchmaking.

        Args:
            connection: The just-authenticated, brand new connection.
            username: The just-authenticated username - the one stable
                identity a pending disconnect is tracked by (see module
                docstring's "WHY DISCONNECT-COUNTDOWN STATE IS TRACKED
                BY USERNAME..." section).
            rating: This connection's own current rating - only used to
                format the resumed assigned_color message, exactly like
                an ordinary fresh join would.

        Returns:
            (match, color) if this was a resume, or None if there was
            no pending disconnect for `username` (the common case) or
            it had already resolved (see module docstring's "A REAL,
            NARROW RACE" section).
        """

        pending = self._pending_disconnects.pop(username, None)
        if pending is None or pending.resolution.done():
            return None

        match = pending.match
        color = pending.color
        match.colors[connection] = color
        pending.resolution.set_result(True)

        opponents = tuple(c for c in match.colors if c is not connection)
        for opponent in opponents:
            await self._protocol.send(opponent, self._protocol.format_opponent_reconnected())

        await self._protocol.send(connection, self._protocol.format_assigned_color(color, rating))
        await self._protocol.send(connection, self._current_board_text(match))
        return match, color

    async def _handle_active_match_disconnect(
        self, match: _Match, connection: ServerConnection, color: Color, username: str
    ) -> None:
        """Called once `connection`'s own `async for message in
        connection` loop has ended (a real ConnectionClosed) during an
        ACTIVE match - see module docstring's "STAGE E2" section for
        the full reasoning behind every decision below.

        Args:
            match: The real _Match `connection` was part of.
            connection: The now-dead connection - never used again
                beyond this method's own opponent-lookup/cleanup.
            color: The color `connection` was playing as.
            username: `connection`'s own authenticated username - the
                key this countdown is tracked under.

        Returns:
            None.

        Registers a real _PendingDisconnect, notifies the still-
        connected opponent(s) once (never on a periodic timer - see
        module docstring's "WIRE MESSAGE" section), then lingers,
        `await`-ing a real future that is resolved externally by
        whichever happens first: a reconnecting connection under the
        SAME username (`_resume_if_pending_disconnect`, above,
        resolves it True) or this instance's own tick-loop check
        (`_check_disconnect_countdowns`, below, resolves it False after
        a real auto-resign). Only once that future resolves does this
        method perform the final `match.colors`/`self._matches`
        cleanup - safe regardless of which outcome occurred: on a
        successful reconnect, `match.colors[connection]` was already
        overwritten by the NEW connection object (see
        `_resume_if_pending_disconnect`), so popping the OLD, dead
        `connection` object here is a harmless no-op that touches
        nothing the new connection depends on.
        """

        loop = asyncio.get_running_loop()
        resolution: "asyncio.Future[bool]" = loop.create_future()
        self._pending_disconnects[username] = _PendingDisconnect(
            match=match, color=color, username=username, disconnected_at=self._clock(), resolution=resolution
        )

        opponents = tuple(c for c in match.colors if c is not connection)
        for opponent in opponents:
            await self._protocol.send(
                opponent, self._protocol.format_opponent_disconnected(self._disconnect_countdown_s)
            )

        await resolution

        match.colors.pop(connection, None)
        if not match.colors:
            # See module docstring's "MATCH CLEANUP ON DISCONNECT"
            # section - both players are gone, stop ticking this match
            # forever.
            self._matches.pop(match.match_id, None)

    async def _check_disconnect_countdowns(self) -> None:
        """Auto-resign every disconnect countdown that has run longer
        than this instance's own `disconnect_countdown_s` with no
        reconnect - see module docstring's "TIMEOUT MECHANISM REUSES
        THE TICK LOOP" and "RESIGN REUSES THE EXISTING GameOver
        MECHANISM" sections for the full reasoning.

        Returns:
            None.
        """

        now = self._clock()
        expired_usernames = [
            username
            for username, pending in self._pending_disconnects.items()
            if (now - pending.disconnected_at) > self._disconnect_countdown_s
        ]
        for username in expired_usernames:
            pending = self._pending_disconnects.pop(username, None)
            if pending is None or pending.resolution.done():
                continue
            # See GameSession.resign's own "GUARDED AGAINST A
            # DOUBLE-RESIGN RACE" docstring section - resign() itself
            # already refuses to overwrite an already-decided winner,
            # so no separate guard is needed here for the case where
            # BOTH players of this match disconnected independently.
            pending.match.session.resign(loser_color=pending.color)
            pending.resolution.set_result(False)

    async def _authenticate(self, username: str, password: str) -> Optional[int]:
        """Sign up (if `username` is new) or log in (if it already
        exists), entirely on this instance's own persistent, single
        worker thread - see module docstring's "WHY UserRepository'S
        OWN SYNCHRONOUS CALLS ARE OFFLOADED..." and "LAZY,
        THREAD-PINNED CONSTRUCTION" sections for the full reasoning.

        Args:
            username: The claimed username from a real, already-parsed
                ParsedAuthCommand.
            password: The claimed password from that same command.

        Returns:
            The account's current rating on success (a brand-new
            account starts at UserRepository.DEFAULT_STARTING_RATING);
            None if `username` already existed and `password` was
            wrong.
        """

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._user_repository_executor, self._authenticate_sync, username, password)

    def _authenticate_sync(self, username: str, password: str) -> Optional[int]:
        """The real, synchronous body of _authenticate - runs
        EXCLUSIVELY on self._user_repository_executor's one worker
        thread. Lazily constructs self._user_repository on its first
        call - by construction, every call to this method already runs
        on the SAME single worker thread, so the object built here on
        the first call is guaranteed to still be on its own owning
        thread for every later call too."""

        if self._user_repository is None:
            self._user_repository = (
                UserRepository(db_path=self._user_repository_db_path)
                if self._user_repository_db_path is not None
                else UserRepository()
            )

        created = self._user_repository.create_account(username, password)
        if not created and not self._user_repository.verify_login(username, password):
            return None

        return self._user_repository.get_rating(username)

    async def _handle_message(
        self, match: _Match, connection: ServerConnection, assigned_color: Color, message: object
    ) -> None:
        """Parse one raw incoming message and dispatch it to the
        matching handler - see module docstring's "JUMP COMMAND
        ROUTING AND REJECTION SCHEME" section for why this can never
        misroute a genuine move command.

        Args:
            match: The real _Match this connection belongs to.
            connection: The connection `message` arrived on.
            assigned_color: The color this connection was assigned when
                matched.
            message: The raw text (or bytes) websockets delivered.

        Returns:
            None.
        """

        try:
            parsed = self._protocol.parse_incoming_command(message)
        except (MalformedCommandError, MalformedJumpCommandError) as exc:
            await self._protocol.send(connection, self._protocol.format_rejection(f"malformed:{exc}"))
            return

        if isinstance(parsed, ParsedJumpCommand):
            await self._handle_jump_command(match, connection, assigned_color, parsed)
        else:
            await self._handle_move_command(match, connection, assigned_color, parsed)

    async def _handle_move_command(
        self, match: _Match, connection: ServerConnection, assigned_color: Color, parsed: ParsedMoveCommand
    ) -> None:
        """Validate and dispatch one ALREADY-PARSED move command - see
        module docstring's "MOVE COMMAND REJECTION SCHEME" for the
        exact rejection responses this sends."""

        if parsed.color is not assigned_color:
            await self._protocol.send(connection, self._protocol.format_rejection("wrong_color"))
            return

        if not self._piece_matches(match, parsed.color, parsed.piece_kind, parsed.from_cell):
            await self._protocol.send(connection, self._protocol.format_rejection("piece_mismatch"))
            return

        # A legal (or engine-rejected) move from here on is entirely
        # handled by the real GameSession/GameEventPublisher/EventBus
        # chain - broadcast to this match's own two connections by
        # self._on_game_event, subscribed once in _create_match.
        match.session.request_move(parsed.from_cell, parsed.to_cell)

    async def _handle_jump_command(
        self, match: _Match, connection: ServerConnection, assigned_color: Color, parsed: ParsedJumpCommand
    ) -> None:
        """Validate and dispatch one ALREADY-PARSED jump command - see
        module docstring's "JUMP COMMAND ROUTING AND REJECTION SCHEME"
        for the exact rejection responses this sends."""

        if parsed.color is not assigned_color:
            await self._protocol.send(connection, self._protocol.format_rejection("wrong_color"))
            return

        if not self._piece_matches(match, parsed.color, parsed.piece_kind, parsed.cell):
            await self._protocol.send(connection, self._protocol.format_rejection("piece_mismatch"))
            return

        accepted = match.session.request_jump(parsed.cell)
        if not accepted:
            await self._protocol.send(connection, self._protocol.format_rejection("jump_rejected"))

    def _piece_matches(self, match: _Match, color: Color, piece_kind: PieceKind, cell: Position) -> bool:
        """Whether a claimed color/piece kind actually matches what's
        on `cell` right now, on this MATCH's own board."""

        piece = match.session.engine.board.piece_at(cell)
        if piece is None:
            return False
        return piece.color is color and piece.kind is piece_kind

    def _on_game_event(self, match: _Match, event: object) -> None:
        """The real EventBus subscriber, bound to its own match at
        subscription time (see _create_match) - see module docstring's
        "WHY THE BROADCASTER BRIDGES A SYNC CALLBACK..." section for
        why this stays synchronous and only SCHEDULES the real send."""

        asyncio.create_task(self._broadcast_event(match, event))

    async def _broadcast_event(self, match: _Match, event: object) -> None:
        """Broadcast the real, structured wire-format event message for
        `event` (if any), THEN the existing board-text snapshot, THEN
        (for MoveAccepted/JumpAccepted/PieceArrived only) the score/
        move-log/elapsed-clock snapshot - to THIS MATCH's own two
        connections only, never every connection on the server."""

        connections: Tuple[ServerConnection, ...] = tuple(match.colors.keys())
        wire_text = self._protocol.format_event(event)
        if wire_text is not None:
            await self._protocol.broadcast(connections, wire_text)
        await self._protocol.broadcast(connections, self._current_board_text(match))
        if isinstance(event, (MoveAccepted, JumpAccepted, PieceArrived)):
            await self._protocol.broadcast(connections, self._current_state_snapshot_text(match))
        if isinstance(event, GameOver):
            # See module docstring's "STAGE D3" section - the single
            # right choke point every real GameOver (king capture,
            # interception, or Stage E2's own auto-resign) already
            # converges on.
            await self._apply_and_notify_rating_update(match, event)

    async def _apply_and_notify_rating_update(self, match: _Match, event: GameOver) -> None:
        """Compute and persist a real ELO update for both of `match`'s
        own players, then notify each of them individually - see module
        docstring's "STAGE D3" section for the full reasoning.

        Args:
            match: The real _Match that just ended.
            event: The real GameOver - `event.winner_color` names the
                winner; the other color is the loser.

        Returns:
            None.
        """

        winner_color = event.winner_color
        loser_color = winner_color.opposite
        winner_username = match.usernames.get(winner_color)
        loser_username = match.usernames.get(loser_color)
        if winner_username is None or loser_username is None:
            # Defensive only - every real match already has both colors
            # populated in `usernames` at construction time (_create_
            # match); this should be unreachable in practice.
            return

        loop = asyncio.get_running_loop()
        winner_old, winner_new, loser_old, loser_new = await loop.run_in_executor(
            self._user_repository_executor, self._apply_elo_update_sync, winner_username, loser_username
        )

        ratings_by_color = {winner_color: (winner_old, winner_new), loser_color: (loser_old, loser_new)}
        for connection, color in match.colors.items():
            old_rating, new_rating = ratings_by_color[color]
            await self._protocol.send(connection, self._protocol.format_rating_update(old_rating, new_rating))

    def _apply_elo_update_sync(self, winner_username: str, loser_username: str) -> Tuple[int, int, int, int]:
        """The real, synchronous body of _apply_and_notify_rating_update
        - runs EXCLUSIVELY on self._user_repository_executor's one
        worker thread, the same one _authenticate_sync already uses
        (see module docstring's "STAGE D3" section for why this is
        required, not merely convenient).

        Args:
            winner_username: The winning player's own username.
            loser_username: The losing player's own username.

        Returns:
            (winner_old_rating, winner_new_rating, loser_old_rating,
            loser_new_rating) - both new ratings already persisted via
            UserRepository.update_rating before this returns.
        """

        winner_old = self._user_repository.get_rating(winner_username)
        loser_old = self._user_repository.get_rating(loser_username)
        winner_new, loser_new = compute_new_ratings(winner_old, loser_old)
        self._user_repository.update_rating(winner_username, winner_new)
        self._user_repository.update_rating(loser_username, loser_new)
        return winner_old, winner_new, loser_old, loser_new

    def _current_state_snapshot_text(self, match: _Match) -> str:
        """The score/move-log/elapsed-clock snapshot for THIS match."""

        score = match.session.score_observer.snapshot()
        log = match.session.moves_log_observer.snapshot()
        clock_ms = match.session.engine.state.clock_ms
        return self._protocol.format_state_snapshot(score, log, clock_ms)

    def _current_board_text(self, match: _Match) -> str:
        """The current board, serialized, for THIS match."""

        return self._protocol.format_board_text(match.session.engine.board)

    async def run_tick_loop(self) -> None:
        """Advance every currently active match by real, measured
        wall-clock time, and check for matchmaking timeouts and
        disconnect-countdown expirations, forever - see module
        docstring's "TICK LOOP NOW ITERATES EVERY ACTIVE MATCH",
        "TIMEOUT MECHANISM", and "STAGE E2 - ... TIMEOUT MECHANISM
        REUSES THE TICK LOOP" sections. Runs independently of any
        client message arriving; intended to be started exactly once,
        as its own background asyncio task, for the lifetime of the
        process (see server/main.py).

        Returns:
            Never returns under normal operation (an infinite loop) -
            ends only if cancelled.
        """

        last_time = time.perf_counter()
        while True:
            await asyncio.sleep(TICK_INTERVAL_S)
            now = time.perf_counter()
            delta_ms = int((now - last_time) * 1000)
            last_time = now
            for match in list(self._matches.values()):
                match.session.wait(delta_ms)
            await self._check_matchmaking_timeouts()
            await self._check_disconnect_countdowns()
