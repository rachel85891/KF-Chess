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

STAGE - SERVER SHUTDOWN HANGS ON A PENDING DISCONNECT COUNTDOWN (fix/
server-shutdown-hang-pending-disconnect, discovered during Stage F2's
own diagnostic work as a real, reproduced hang, not a hypothetical
one): `_handle_active_match_disconnect` (Stage E2) deliberately `await`s
`pending.resolution` with NO timeout of its own - correct for the
countdown feature itself, since that future is meant to be resolved
externally, whenever a reconnect or a real countdown expiry happens
(see that method's own docstring). The bug this stage fixes: NEITHER
of those two things happens when the SERVER ITSELF is what's shutting
down - a graceful shutdown intends to stop the whole process, not wait
out however many players happen to have a countdown running at that
exact moment. websockets 16.1.1's own `Server.close()` - the exact
mechanism `async with server:` invokes on exit (see
`websockets.asyncio.server.Server.__aexit__`, and this project's own
server/main.py, which uses that context-manager form) - awaits
`asyncio.wait(self.handlers.values())`, i.e. every connection handler
task websockets itself spawned, before it considers the server closed.
A `handle_connection` coroutine parked inside `_handle_active_match_
disconnect`'s `await resolution` is exactly such a handler task -
`close()` (and therefore `wait_closed()`) cannot return until that
`await` does, which nothing was previously arranging to happen sooner
than `disconnect_countdown_s` (20 real seconds, by default) - or,
whenever no tick loop happens to be running to ever call
`_check_disconnect_countdowns` at all (the common case for most of
this project's own integration tests, and for ANY scenario where a
reconnect would otherwise have cancelled the countdown), not at all,
ever - reproduced directly: a real server, matched, both clients
disconnected, then `server.close(); await server.wait_closed()`
(unmodified production code) measurably fails to return within an 8
real-second bound.

`GameServer.shutdown()` (new) is the fix: resolves every currently-
pending disconnect countdown immediately, so every such lingering
`handle_connection` task returns right away instead of blocking
`close()`/`wait_closed()`. The caller (server/main.py's own
composition root, or a test's own teardown - see each's own updated
shutdown sequence) is responsible for calling this BEFORE `server.
close()` - `shutdown()` has no way to hook into `close()`'s own
internals itself (GameServer never holds a reference to the `Server`
object; only `handle_connection` was ever handed to `websockets.
serve`), so ordering is the caller's own explicit responsibility, in
exactly the one place each caller already decides "we are shutting
down now."

WHY RESOLVED (NOT CANCELLED), AND WHY `False` WITHOUT `session.
resign()` - SEE `shutdown()`'s OWN DOCSTRING for the full reasoning;
summarized here: resolving (rather than cancelling) lets `_handle_
active_match_disconnect`'s existing post-`await` cleanup
(`match.colors.pop(...)`/`self._matches.pop(...)`) run completely
unmodified, with no new cancellation-handling code path to reason
about. `False` is reused as the already-established "no reconnect
happened" signal (mirroring `_check_disconnect_countdowns`'s own real
timeout-expiry path) rather than inventing a third sentinel - but,
deliberately, `session.resign()` is NEVER called here and no GameOver
is ever published: the server process itself ending is an operational
event, not a player-meaningful game outcome, and treating it as an
auto-resign would silently and permanently penalize a player's real
ELO rating (via `_apply_and_notify_rating_update`) for a server
restart/deploy that had nothing to do with their own play - a false
and undesirable side effect this fix specifically avoids by resolving
the future directly rather than routing shutdown through the SAME
code path real countdown expiry uses.

STAGE F4 - WIRING STAGE F3's ROOM CHOICE INTO A REAL GameSession
(feature/rooms-f4-gameserver-wiring): before this stage, every
authenticated connection unconditionally entered matchmaking - Stage
F3 built the wire vocabulary for a real PLAY/CREATE_ROOM/JOIN_ROOM
choice but wired it into nothing. This is the first stage in the
Rooms/Viewers track to touch GameServer at all - E1's matchmaking and
E2's disconnect-countdown/reconnect behavior for connections that still
choose PLAY must keep working exactly as they did before this stage,
which is why this stage's own scope is deliberately narrow (see below).

A REAL, CONSEQUENTIAL PROTOCOL CHANGE, NOT A SIDE EFFECT TO MINIMIZE
SILENTLY: every authenticated, non-resumed connection now reads ONE
MORE message (its own room choice) before proceeding - mirrors this
class's own "WHY 'server_full'... IS REMOVED ENTIRELY" precedent
above: a real wire-protocol change legitimately requires updating
every pre-existing test that authenticates and then waits directly for
assigned_color/searching_for_opponent with no room-choice message ever
sent (there was none to send, before this stage) - flagged here loudly,
exactly like that earlier precedent, not treated as an unrelated
cleanup (see this stage's own commit history for the exact test-helper
migration this required).

WHY THE ROOM-CHOICE MESSAGE IS READ ONLY IN THE NON-RESUMED BRANCH,
NEVER FOR A Stage-E2 RECONNECT: `_resume_if_pending_disconnect`
resuming a connection into its OWN existing match/color is not a fresh
choice at all - the player already chose PLAY/CREATE_ROOM/JOIN_ROOM
once, whenever they originally joined that same, still-running match;
asking them to choose again on reconnect would be meaningless (there is
no second "which mode" decision to make - they are rejoining the exact
game they already chose into), and Stage E2's own resumed connection
already proceeds straight into the shared message loop with zero
special-casing there. This overrides Implementation_Plan.md's own
implicit assumption that every connection makes a fresh choice - a
reconnect, by this project's own existing E2 design, simply is not one.

WHY PLAY DOES NOT ROUTE THROUGH SessionCoordinator.find_match, DESPITE
Implementation_Plan.md's OWN LITERAL WORDING (a deliberate override,
mirroring Stage F3's own identical precedent of overriding that same
document's stale wording): SessionCoordinator.find_match's real,
already-tested contract (Stage F2) is "attempt exactly one pairing,
synchronously, no timeout concept, no disconnect-while-waiting
handling of its own" - `_wait_for_match`/`_attempt_matchmaking`'s real,
already-tested contract is meaningfully richer: draining every
available pair per call (not just the newest arrival), a real
60-second timeout via the tick loop, and a real disconnect-while-queued
race (`_wait_for_match`'s own `asyncio.wait` against a live `recv()`).
Rebuilding PLAY to fit find_match's narrower shape would mean either
throwing away already-correct, already-tested production behavior for
zero benefit, or reimplementing timeout/disconnect-while-waiting
handling a SECOND time inside SessionCoordinator - directly
contradicting this whole track's own standing "E1/E2 must keep working
exactly the same" requirement. `self._matchmaking_queue` therefore
remains PLAY's own real collaborator, completely unchanged;
`self._session_coordinator` (new, this stage) is used ONLY for
CREATE_ROOM/JOIN_ROOM - two separate collaborators for two genuinely
different mechanisms is the honest shape here, not a shortcut.
SessionCoordinator's own module docstring already anticipates a FUTURE
stage fully unifying them behind a distributed backend; this stage is
not that stage.

_construct_match IS THE ONE PLACE A _Match IS EVER BUILT (see that
method's own docstring): both `_create_match` (PLAY, via the
matchmaking queue) and this stage's own room-completion branch (inside
`_handle_room_choice`'s JoinRoomCommand/GUEST case) call it - this is
what "reuse existing construction logic, not duplicate it"
(Implementation_Plan.md's own F4 acceptance criterion) concretely
means: one extraction, two callers, zero duplicated construction code.

HOST=WHITE, GUEST=BLACK (mirrors "COLOR ASSIGNMENT FOR A MATCHED PAIR"
above, applied to a room instead of the matchmaking queue): whoever
created the room necessarily exists, and chose to wait, before anyone
else could ever join it - an unambiguous, real join-order exactly
analogous to matchmaking's own "earlier-queued becomes White" rule,
just with a room's own host/guest relationship standing in for the
queue's own earlier/later relationship.

self._pending_rooms AND self._waiting_room_futures - GameServer's OWN
BOOKKEEPING, NOT Room's: Room (server/application/room.py) deliberately
knows nothing about usernames or connections at all (see that module's
own docstring) - but constructing a real _Match for a completed room
needs BOTH the host's own connection AND username, and something must
wake the host's own `_wait_for_room_ready` the moment a guest actually
joins. `self._pending_rooms: Dict[str, Tuple[ServerConnection, str]]`
(keyed by room code) supplies the first; `self._waiting_room_futures:
Dict[str, "asyncio.Future[Optional[_Match]]"]` (also keyed by room
code - a room's own host has no WaitingPlayer entry to key off of the
way matchmaking's own `_waiting_futures` keys by connection) supplies
the second - both mirror `_waiting_futures`'s own established shape and
invariants exactly, just keyed by code instead of connection.

ACCEPTED GAP - AN ABANDONED ROOM CAN NEVER BE RECLAIMED (flagged here
explicitly, mirroring this project's own established "accepted gaps,
not oversights" convention, e.g. Stage E2's own "no general reconnect"
gap): if a host disconnects before any guest ever joins,
`_wait_for_room_ready` returns None and `self._pending_rooms` is
cleaned up for that code - but the real Room object itself remains
forever inside `self._session_coordinator`'s own internal registry,
since the SessionCoordinator Protocol (deliberately, per Stage F2's own
scope) exposes no removal method. A room code can therefore never be
reused or reclaimed once created, even abandoned - and, relatedly, if a
GUEST joins that same abandoned code before this stage's own
`host_connection is None` check runs, `SessionCoordinator.join_room`
has ALREADY (irreversibly) recorded that guest identity as a real
occupant of the now-host-less Room, even though this connection is
correctly told "room_not_found" and closed - a real, accepted
consequence of the identical "no removal method" gap, not a separate
bug. Extending SessionCoordinator's own Protocol with a removal method
is explicitly out of THIS stage's scope (it was asked to WIRE F2's
existing methods, not add new ones to it).

ACCEPTED SCOPE BOUNDARY - A VIEWER'S CONNECTION IS CLOSED RIGHT AFTER
"room_joined:viewer" (SUPERSEDED BY STAGE F5, BELOW - kept here as
historical record of Stage F4's own original, deliberately narrower
scope): real spectating (receiving board/event broadcasts, being
excluded from move validation) was Stage F5 (viewer move-rejection) and
Stage F6 (N-variable broadcast fan-out)'s own explicit, separate job -
Stage F4's task was to wire CREATE_ROOM/JOIN_ROOM into a real
GameSession for exactly a host+guest pair, not to build spectator
infrastructure two stages early.

STAGE F5 - A VIEWER ACTUALLY STAYS CONNECTED AND WATCHES
(feature/rooms-f5-viewer-role-enforcement): replaces Stage F4's own
"close the connection right after room_joined:viewer" placeholder - a
viewer now joins the SAME shared `async for message in connection`
loop every player already uses, with `assigned_color` (renamed
`Optional[Color]` throughout this chain) set to `None` to mean "this
connection is a viewer, not a player."

A GENUINE OVERLAP BETWEEN F5's AND F6's OWN STATED SCOPES, RESOLVED
HERE (Implementation_Plan.md's own F5 acceptance criteria already say
"the viewer still receives all normal broadcasts," which `_broadcast_
event`'s own pre-existing `tuple(match.colors.keys())` - exactly two
connections, hardcoded, by construction - could never satisfy without
ALSO being the exact extension F6's own task literally describes: "audit
every broadcast loop... never a hardcoded assumption of exactly 2." This
is a real inconsistency in a document written before F1/F2/F4 were
actually built, not something resolvable by picking one document's
wording over the other. RESOLUTION: F5 performs the ONE minimal
extension `_broadcast_event` needs to make ITS OWN narrow "2 players + 1
viewer" acceptance test true (`tuple(match.colors.keys()) +
tuple(match.viewer_connections)`) - nothing broader. F6 remains
responsible for the wider audit: every OTHER loop in this file that
might assume "exactly 2" (if any exist beyond `_broadcast_event`), and
the broader "2 players + 3 viewers = 5 connections, all treated
identically" correctness test Implementation_Plan.md's own F6 section
describes - deliberately NOT attempted in this stage.

`assigned_color` WIDENED TO `Optional[Color]` THROUGHOUT THE CHAIN
(`_handle_room_choice`'s own return type, `_handle_message`/
`_handle_move_command`/`_handle_jump_command`'s own parameter) - NO NEW
VIEWER-SPECIFIC BRANCH ANYWHERE: a real, parsed `ParsedMoveCommand.
color`/`ParsedJumpCommand.color` is always a genuine `Color`, never
`None` - the EXISTING `if parsed.color is not assigned_color: reject
("wrong_color")` check in both `_handle_move_command` and
`_handle_jump_command` therefore already, correctly, unconditionally
rejects every move/jump from a viewer (`assigned_color is None`)
regardless of which color it claims - Implementation_Plan.md's own "a
third value on an existing mechanism, not a new one" made completely
literal: zero new code paths in either handler.

`self._room_matches: Dict[str, _Match]` - A SEPARATE DICT FROM
`self._pending_rooms`, WITH A DELIBERATELY DIFFERENT LIFETIME:
`self._pending_rooms` (Stage F4) tracks ONLY the "waiting for a first
guest" phase of a room's life, and is popped the moment that phase ends
(a real GUEST joins, or the host disconnects first) - it has nothing
left to say once a room is complete. `self._room_matches` begins its
own life at EXACTLY that same moment (populated inside the JoinRoomCommand/
GUEST branch, immediately after `_construct_match` succeeds) and answers
a different, ongoing question for the REST of that match's real
lifetime: "which real _Match does this room code now point to" - the
one thing a THIRD, later-arriving VIEWER actually needs to find.

ACCEPTED, DEFERRED GAP - `self._room_matches` ENTRIES ARE NEVER POPPED,
EVEN AFTER A MATCH ENDS (mirrors Stage F4's own identical "abandoned
room can never be reclaimed" gap precisely): this stage's own scope is
wiring viewers into a match that is currently LIVE, not building
match-lifecycle cleanup for one that has already ended - `_room_matches`
entries, like `SessionCoordinator`'s own room registry, simply grow for
the lifetime of the process. A viewer joining a room code whose match
already ended would still find a real (but finished) `_Match` here and
join it as a spectator of its own final state - not incorrect, merely
unbounded memory growth, explicitly left to a future stage.

ACCEPTED "PHANTOM ROOM" EDGE CASE - A THIRD JOIN_ROOM ON AN ABANDONED
CODE GETS `room_not_found`, NOT A CRASH OR A VIEWER ROLE (a further,
direct consequence of Stage F4's own already-accepted gap, not a new
bug): if a host disconnects before any guest ever joins, a SECOND
connection JOIN_ROOM-ing that same code is already told `room_not_found`
(Stage F4) - but `SessionCoordinator.join_room` has, by then,
irreversibly recorded that second identity as a real GUEST occupant of
the now host-less Room (Stage F4's own "no removal method" gap). A
THIRD connection JOIN_ROOM-ing that SAME code therefore reaches
`Role.VIEWER` from `SessionCoordinator`'s own, entirely correct,
capacity rules (the Room genuinely shows 2 occupants) - but
`self._room_matches.get(code)` is `None`, because no real `_Match` was
ever constructed for this code (the GUEST branch's own
`host_connection is None` check returned before ever reaching
`_construct_match`). This connection is therefore treated identically
to an unknown code (`room_not_found`, closed) - `self._room_matches`
being the definitive "does a real match exist" signal, decoupled from
SessionCoordinator's own Room-capacity bookkeeping, is exactly what
makes this the correct outcome rather than a crash or a silently-joined
viewer with nothing to watch.

A VIEWER'S OWN DISCONNECT IS A COMPLETE NON-EVENT FOR THE MATCH: unlike
a real player (Stage E2's disconnect countdown/auto-resign), a viewer
disconnecting (`color is None` in `handle_connection`'s own post-
message-loop cleanup) never calls `_handle_active_match_disconnect` at
all - only removes itself from `match.viewer_connections` - the two
real players are entirely unaffected either way, and that mechanism
exists to protect an actual PLAYER's own match outcome, not to track
who is merely watching.

STAGE F6 - BROADCAST-CORRECTNESS AUDIT FOR A VARIABLE NUMBER OF VIEWERS
(feature/rooms-f6-broadcast-audit): Stage F5 already made the ONE
change actually required for its own narrow "2 players + 1 viewer"
acceptance test to pass (`_broadcast_event`'s own `connections` tuple
gained `+ tuple(match.viewer_connections)`) and explicitly deferred two
things to this stage: a real audit of every OTHER place in this file
that sends to more than one connection at once, and the broader
"2 players + 3 viewers = 5 connections, all treated identically"
correctness test. This stage performed both - re-running
the same grep used to scope this task (matching "for connection",
"connections:", "connections =", and "self._protocol.broadcast")
against server/application/game_server.py directly (plus a second
pass for `match.colors`-adjacent iteration the first grep's own literal
wording could miss, e.g. `for c in match.colors`) and reading every
result, not merely accepting Stage F5's own prior conclusion on faith.
THE AUDIT ITSELF - every location found, and why each is correct
exactly as it stands today:
  - `_broadcast_event`'s own `connections` tuple (`tuple(match.colors.
    keys()) + tuple(match.viewer_connections)`) - the ONE genuine "send
    to every connection currently in this match" loop in the entire
    file - already fixed in Stage F5, RE-VERIFIED HERE at N=3 viewers
    (5 total connections), not just Stage F5's own N=1 case (see this
    stage's own new `test_two_players_and_three_viewers_all_five_
    connections_receive_every_broadcast_identically`, tests/
    integration/server/test_rooms_wiring.py) - no further change
    needed.
  - `_handle_active_match_disconnect`'s and `_resume_if_pending_
    disconnect`'s own `opponents = tuple(c for c in match.colors if c
    is not connection)` - CORRECTLY scoped to `match.colors` (real
    players) ONLY, deliberately excluding viewers: "opponent_
    disconnected"/"opponent_reconnected" are Stage E2's own real-
    player-only disconnect-countdown mechanism - a viewer has no
    personal stake in a PLAYER's own countdown (it is not "their"
    opponent in any sense this mechanism means), and Stage F5/F6
    neither extended nor were asked to extend that mechanism to
    viewers. Not a bug; not touched.
  - `_apply_and_notify_rating_update`'s own `for connection, color in
    match.colors.items():` - CORRECTLY scoped to `match.colors` ONLY: a
    viewer has no rating in this match at all (ratings belong to the
    two real players who actually played it) - there is nothing to
    notify a viewer of here, by definition, not by oversight.
  - The tick loop (`run_tick_loop`'s own `for match in list(self.
    _matches.values()): match.session.wait(delta_ms)`) - never
    references any connection at all; it advances `GameSession` state
    only, entirely unaffected by however many viewers (or players) are
    currently watching. Nothing to fix.
  - `ProtocolHandler.broadcast` (server/presentation/protocol_
    handler.py) - independently re-verified: takes a plain `Iterable[
    ServerConnection]` and loops over it (`for connection in
    connections: await self.send(connection, text)`) with zero
    hardcoded count assumption anywhere in its own body - already
    correctly N-agnostic, confirmed directly rather than assumed from
    its own docstring's claim.
CONCLUSION: no production code in this file needed to change beyond
this docstring section itself - Stage F5's own single, minimal
`_broadcast_event` fix was already complete and correct for any N, not
merely N=1. This stage's own real, required deliverable is exactly this
audit-and-document work, plus the new N=3 test proving it, per this
stage's own explicit task framing ("more important here than any new
code").
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import functools
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple, Union

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
from server.application.room import Role
from server.application.session_coordinator import InMemorySessionCoordinator, SessionCoordinator
from server.persistence.user_repository import SqliteUserRepository
from server.persistence.user_repository_protocol import UserRepository
from server.presentation.auth_command import MalformedAuthCommandError
from server.presentation.connection_manager import ConnectionManager
from server.presentation.move_command import MalformedCommandError, ParsedMoveCommand
from server.presentation.protocol_handler import SEARCHING_FOR_OPPONENT_MESSAGE, ProtocolHandler
from server.presentation.room_choice_command import (
    CreateRoomCommand,
    JoinRoomCommand,
    MalformedRoomChoiceCommandError,
    PlayCommand,
)

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
    # Stage F5 - see module docstring's "STAGE F5" section: `colors`
    # above holds exactly the two real players, UNCHANGED by this
    # stage; this new field holds every OTHER connection currently
    # watching this same match, in join order - appended to as each
    # viewer joins (`_handle_room_choice`'s JoinRoomCommand/VIEWER
    # branch), never removed except on that viewer's own disconnect
    # (`handle_connection`'s own post-message-loop cleanup).
    viewer_connections: List[ServerConnection] = field(default_factory=list)


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
        session_coordinator: Optional[SessionCoordinator] = None,
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
            session_coordinator: The SessionCoordinator this instance
                delegates CREATE_ROOM/JOIN_ROOM to - see module
                docstring's "STAGE F4" section for why PLAY does NOT
                also go through this (matchmaking_queue, above, remains
                the real collaborator for PLAY, completely unchanged).
                Defaults to a fresh, real InMemorySessionCoordinator -
                injectable (DIP) for tests that want to control (or
                directly inspect) room creation/joining.
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
        self._session_coordinator: SessionCoordinator = (
            session_coordinator if session_coordinator is not None else InMemorySessionCoordinator()
        )

        self._matches: Dict[int, _Match] = {}
        self._next_match_id = 1
        # Populated in _wait_for_match, resolved either by _create_match
        # (with the real _Match) or _check_matchmaking_timeouts (with
        # None) - see module docstring's "TIMEOUT MECHANISM" and
        # "DISCONNECTION WHILE WAITING" sections.
        self._waiting_futures: Dict[ServerConnection, "asyncio.Future[Optional[_Match]]"] = {}

        # Stage F4 - a room's own host (CreateRoomCommand) is tracked
        # here, keyed by room code, purely as GameServer's OWN
        # bookkeeping - see module docstring's "STAGE F4" section for
        # why Room itself (server/application/room.py) deliberately
        # knows nothing about usernames/connections at all, and why this
        # class - the one place a username IS already available - is
        # the right, and only, place to remember "who is this room's
        # own host" for when a guest actually joins.
        self._pending_rooms: Dict[str, Tuple[ServerConnection, str]] = {}
        # Mirrors `_waiting_futures` above exactly, keyed by room code
        # instead of by connection (a room's own host has no `WaitingPlayer`
        # entry to key off of - the code IS the natural key here) -
        # resolved either by a real JOIN_ROOM (with the real _Match) or
        # the host disconnecting first (with None) - see
        # `_wait_for_room_ready`'s own docstring.
        self._waiting_room_futures: Dict[str, "asyncio.Future[Optional[_Match]]"] = {}
        # Stage F5 - see module docstring's "STAGE F5" section for why
        # this is a SEPARATE dict from `self._pending_rooms` above (that
        # one tracks only the "waiting for a first guest" phase, and is
        # popped once a room is complete; this one tracks "which real
        # _Match does this room code now point to", for the entire
        # remaining lifetime of that match) - populated exactly once, at
        # the moment a room's SECOND occupant (the GUEST) completes it,
        # and consulted by every subsequent VIEWER arrival for that same
        # code. Deliberately never popped when a match ends (an accepted,
        # deferred gap - see module docstring's own "STAGE F5" section).
        self._room_matches: Dict[str, _Match] = {}

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
            # Stage F4 - a reconnecting (resumed, above) connection never
            # reaches this branch at all: a reconnect is not a fresh
            # choice, by this project's own existing Stage E2 design (see
            # module docstring's "STAGE F4" section) - only a genuinely
            # new join makes a PLAY/CREATE_ROOM/JOIN_ROOM choice.
            try:
                raw_room_choice = await connection.recv()
            except ConnectionClosed:
                # The client disconnected before ever choosing - unlike
                # the AUTH-parsing ConnectionClosed branch far above,
                # self._connection_manager.add(connection) has ALREADY
                # run by this point, so it must be undone here.
                self._connection_manager.remove(connection)
                return

            try:
                parsed_choice = self._protocol.parse_incoming_room_choice(raw_room_choice)
            except MalformedRoomChoiceCommandError as exc:
                await self._protocol.send(connection, self._protocol.format_rejection(f"malformed:{exc}"))
                await connection.close()
                self._connection_manager.remove(connection)
                return

            outcome = await self._handle_room_choice(connection, parsed_choice, parsed_auth.username, rating)
            if outcome is None:
                self._connection_manager.remove(connection)
                return
            match, color = outcome

        try:
            async for message in connection:
                await self._handle_message(match, connection, color, message)
        except ConnectionClosed:
            pass

        if color is not None:
            # Stage E2 - a disconnect during an ACTIVE match no longer
            # falls straight to cleanup: see module docstring's "STAGE
            # E2" section and _handle_active_match_disconnect's own
            # docstring for the full reasoning (a real, visible
            # countdown, with narrow, scoped support for the SAME
            # username reconnecting during it). This does NOT affect a
            # disconnect while merely WAITING in the matchmaking queue
            # at all - that path is entirely separate, inside
            # _wait_for_match, above, unchanged by this stage.
            await self._handle_active_match_disconnect(match, connection, color, parsed_auth.username)
        else:
            # Stage F5 - `color is None` means `connection` is a VIEWER
            # (see module docstring's "STAGE F5" section) - a viewer
            # disconnecting is a complete non-event for the match
            # itself: the two real players are entirely unaffected
            # either way, so this never starts a countdown or triggers
            # auto-resign (that mechanism exists for actual players
            # only) - just stop watching.
            if connection in match.viewer_connections:
                match.viewer_connections.remove(connection)
        self._connection_manager.remove(connection)

    async def _handle_room_choice(
        self,
        connection: ServerConnection,
        parsed_choice: Union[PlayCommand, CreateRoomCommand, JoinRoomCommand],
        username: str,
        rating: int,
    ) -> Optional[Tuple[_Match, Optional[Color]]]:
        """Branch on a freshly-parsed post-AUTH room choice - see module
        docstring's "STAGE F4" and "STAGE F5" sections for the full
        reasoning behind every branch below. Mirrors
        `_resume_if_pending_disconnect`'s own
        `Optional[Tuple[_Match, Color]]` return convention, widened to
        `Optional[Color]` (Stage F5): a real (match, color) once this
        connection has a live match to join `handle_connection`'s own
        shared message loop with as a PLAYER, (match, None) if it joins
        that SAME shared loop as a VIEWER instead (see module
        docstring's "STAGE F5" section for what `None` means at every
        downstream call site this reaches), or plain `None` if this
        connection has ALREADY been fully handled (rejected, timed out,
        or abandoned) and `handle_connection` should simply clean up and
        return.

        Args:
            connection: The just-authenticated connection making this
                choice.
            parsed_choice: The real PlayCommand/CreateRoomCommand/
                JoinRoomCommand `handle_connection` already parsed.
            username: This connection's own username.
            rating: This connection's own current rating.

        Returns:
            (match, color) if this connection now has a live match to
            join the shared message loop with (color is None for a
            viewer - Stage F5); None if this connection has already been
            fully handled and nothing more remains to do for it.
        """

        if isinstance(parsed_choice, PlayCommand):
            # The EXISTING matchmaking path (Stage E1/E2), byte-for-byte
            # unchanged - see module docstring's "STAGE F4" section for
            # why this does NOT also go through self._session_coordinator.
            await self._protocol.send(connection, SEARCHING_FOR_OPPONENT_MESSAGE)

            match = await self._wait_for_match(connection, username, rating)
            if match is None:
                # Timed out (the periodic check already sent the
                # timeout message and closed the connection) or
                # disconnected while still queued - either way, nothing
                # further to do here.
                return None

            color = match.colors[connection]
            await self._protocol.send(connection, self._protocol.format_assigned_color(color, rating))
            await self._protocol.send(connection, self._current_board_text(match))
            return match, color

        if isinstance(parsed_choice, CreateRoomCommand):
            code = self._session_coordinator.create_room(connection)
            self._pending_rooms[code] = (connection, username)
            await self._protocol.send(connection, self._protocol.format_room_created(code))

            match = await self._wait_for_room_ready(connection, code)
            if match is None:
                # The host disconnected before any guest ever joined -
                # see module docstring's "STAGE F4" section's own
                # accepted-gap note: the Room itself lives on forever
                # inside self._session_coordinator (no removal method
                # exists to reclaim it), but THIS instance's own
                # bookkeeping for it is cleaned up here.
                self._pending_rooms.pop(code, None)
                return None

            color = match.colors[connection]
            await self._protocol.send(connection, self._protocol.format_assigned_color(color, rating))
            await self._protocol.send(connection, self._current_board_text(match))
            return match, color

        # JoinRoomCommand
        result = self._session_coordinator.join_room(parsed_choice.code, connection)
        if result is None:
            await self._protocol.send(connection, self._protocol.format_room_not_found())
            await connection.close()
            return None

        if result.role is Role.VIEWER:
            # Stage F5 - replaces Stage F4's own "send room_joined:
            # viewer, close, return" placeholder entirely: a viewer now
            # actually stays connected and watches. `self._room_matches`
            # (not SessionCoordinator's own Room, which knows nothing
            # about which real _Match a code maps to) is the definitive
            # answer to "does a real match exist for this code yet" -
            # see module docstring's "STAGE F5" section for the "phantom
            # room" edge case this None-check exists to catch: a THIRD
            # connection can reach Role.VIEWER (per SessionCoordinator's
            # own room-capacity rules) for a code whose host already
            # vanished before any real match was ever constructed
            # (Stage F4's own already-accepted gap) - this is that same
            # gap's further consequence, not a new bug.
            match = self._room_matches.get(parsed_choice.code)
            if match is None:
                await self._protocol.send(connection, self._protocol.format_room_not_found())
                await connection.close()
                return None

            match.viewer_connections.append(connection)
            await self._protocol.send(connection, self._protocol.format_room_joined(Role.VIEWER.value))
            # A viewer joining mid-game needs to see the CURRENT board
            # immediately, not wait for the next event - mirrors every
            # other join path's own "send the current board text right
            # after the role message" convention throughout this file.
            await self._protocol.send(connection, self._current_board_text(match))
            # None here IS the "third value on wrong_color's existing
            # mechanism" Implementation_Plan.md's own F5 section
            # describes - see _handle_move_command's own docstring.
            return match, None

        # result.role is Role.GUEST
        host_connection, host_username = self._pending_rooms.pop(parsed_choice.code, (None, None))
        if host_connection is None:
            # The host itself already disconnected while waiting (see
            # module docstring's "STAGE F4" section's own accepted-gap
            # note) - the Room SessionCoordinator just added this
            # identity to as a GUEST is now permanently stranded (no
            # removal method exists to undo that either), but there is
            # no live host connection left to ever construct a real
            # match with, so this is treated identically to an unknown
            # code from this connection's own point of view.
            await self._protocol.send(connection, self._protocol.format_room_not_found())
            await connection.close()
            return None

        # Host=White, Guest=Black - see module docstring's "STAGE F4"
        # section: whoever created the room necessarily existed, and
        # chose to wait, before anyone could join it - an unambiguous,
        # real join-order analogous to matchmaking's own "earlier-queued
        # becomes White" rule.
        match = self._construct_match(host_connection, host_username, connection, username)
        # Stage F5 - the room is now COMPLETE (host+guest both real) -
        # this is the exact moment `self._room_matches` is populated,
        # see module docstring's "STAGE F5" section for why this is a
        # separate dict from `self._pending_rooms` (already popped,
        # above) and why it is never popped again itself.
        self._room_matches[parsed_choice.code] = match
        future = self._waiting_room_futures.pop(parsed_choice.code, None)
        if future is not None and not future.done():
            future.set_result(match)

        await self._protocol.send(connection, self._protocol.format_room_joined(Role.GUEST.value))
        color = match.colors[connection]
        await self._protocol.send(connection, self._protocol.format_assigned_color(color, rating))
        await self._protocol.send(connection, self._current_board_text(match))
        return match, color

    async def _wait_for_room_ready(self, connection: ServerConnection, code: str) -> Optional[_Match]:
        """Wait for either a real guest to join this room or this
        (host) connection disconnecting/sending something unexpected
        while still waiting - mirrors `_wait_for_match`'s own
        recv-task/future-task race exactly (see that method's own
        "DISCONNECTION WHILE WAITING" module docstring section), keyed
        by room code instead of by connection.

        Args:
            connection: The host connection now waiting for a guest.
            code: This room's own real code.

        Returns:
            The real _Match a guest joined this room into, or None if
            the host disconnected (or sent something unexpected) before
            any guest ever joined.
        """

        loop = asyncio.get_running_loop()
        match_future: "asyncio.Future[Optional[_Match]]" = loop.create_future()
        self._waiting_room_futures[code] = match_future

        recv_task = asyncio.ensure_future(connection.recv())
        match_task = asyncio.ensure_future(match_future)
        done, _pending = await asyncio.wait({recv_task, match_task}, return_when=asyncio.FIRST_COMPLETED)
        self._waiting_room_futures.pop(code, None)

        if match_task in done:
            recv_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, ConnectionClosed):
                await recv_task
            return match_task.result()

        # recv_task completed first - the host disconnected, or sent
        # something unexpected, while still waiting for a guest.
        match_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await match_task
        with contextlib.suppress(ConnectionClosed):
            recv_task.result()
        return None

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

    def _construct_match(
        self,
        first_connection: ServerConnection,
        first_username: str,
        second_connection: ServerConnection,
        second_username: str,
    ) -> _Match:
        """Construct a real, fresh GameSession for exactly this pair,
        assign colors (first=White, second=Black - see module
        docstring's "COLOR ASSIGNMENT FOR A MATCHED PAIR" section for
        matchmaking's own join-order reasoning, and its "STAGE F4"
        section for the identical reasoning applied to a room's own
        host/guest join order instead), subscribe this match's own
        broadcaster, and register it in `self._matches` - the ONE place
        a `_Match` is ever built, whether the pairing came from
        matchmaking (`_create_match`, below, a thin wrapper around this)
        or from a completed room (Stage F4's own `_construct_match`
        call inside the JoinRoomCommand/GUEST branch of
        `handle_connection`) - see module docstring's "STAGE F4" section
        for why this extraction, not two separate near-duplicate
        construction blocks, is what "reuse existing construction
        logic" concretely means here.

        Args:
            first_connection: The connection that becomes White.
            first_username: That connection's own username.
            second_connection: The connection that becomes Black.
            second_username: That connection's own username.

        Returns:
            The newly-constructed, already-registered _Match. Does NOT
            itself wake up anything waiting on a match to exist
            (matchmaking's own `_waiting_futures` and a room's own
            `_waiting_room_futures` are each resolved by their own
            respective caller, immediately after this returns) - this
            method's own job stops at "the match now exists."
        """

        match_id = self._next_match_id
        self._next_match_id += 1
        session = self._session_factory()
        colors: Dict[ServerConnection, Color] = {first_connection: Color.WHITE, second_connection: Color.BLACK}
        usernames: Dict[Color, str] = {Color.WHITE: first_username, Color.BLACK: second_username}
        match = _Match(match_id=match_id, session=session, colors=colors, usernames=usernames)
        self._matches[match_id] = match

        for event_type in _BROADCAST_EVENT_TYPES:
            session.event_bus.subscribe(event_type, functools.partial(self._on_game_event, match))

        return match

    def _create_match(self, first: WaitingPlayer, second: WaitingPlayer) -> None:
        """Construct a match for this matched matchmaking pair (via
        `_construct_match`, above) and wake up both connections' own
        handle_connection coroutines with the result.

        Args:
            first: The earlier-joined of the matched pair - becomes
                White.
            second: The later-joined of the matched pair - becomes
                Black.

        Returns:
            None.
        """

        match = self._construct_match(first.connection_id, first.username, second.connection_id, second.username)

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

    async def shutdown(self) -> None:
        """Resolve every currently-pending disconnect countdown so no
        `handle_connection` coroutine is left blocked on `await
        resolution` (see `_handle_active_match_disconnect`'s own
        docstring) when the SERVER ITSELF is shutting down - discovered
        during Stage F2's diagnostic work as a real, reproducible hang
        (see this method's own "STAGE - SERVER SHUTDOWN" module
        docstring section for the full evidence and reasoning). The
        caller (server/main.py's own composition root, or a test's own
        teardown) is expected to call this BEFORE `server.close()`/
        `await server.wait_closed()` - see module docstring for why
        that ordering matters.

        Returns:
            None.

        RESOLVED AS `False` (mirrors `_check_disconnect_countdowns`'s
        own timeout-expiry signal), BUT WITHOUT calling `session.
        resign()` or publishing a GameOver - see module docstring's
        "STAGE - SERVER SHUTDOWN" section for why an auto-resign/ELO
        update/broadcast side effect is deliberately NOT triggered
        here: the value itself is never actually read by
        `_handle_active_match_disconnect` (only `.done()` is checked
        elsewhere, by `_resume_if_pending_disconnect`) - `False` is
        simply reused as the existing "no reconnect" convention rather
        than inventing a third sentinel value. Resolving (rather than
        cancelling) the future lets `_handle_active_match_disconnect`'s
        own existing, already-tested post-resolution cleanup
        (`match.colors.pop(...)`/`self._matches.pop(...)`) run exactly
        as it already does on a real timeout, with zero new code paths
        to reason about in that method.
        """

        for pending in list(self._pending_disconnects.values()):
            if not pending.resolution.done():
                pending.resolution.set_result(False)
        self._pending_disconnects.clear()

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
                SqliteUserRepository(db_path=self._user_repository_db_path)
                if self._user_repository_db_path is not None
                else SqliteUserRepository()
            )

        created = self._user_repository.create_account(username, password)
        if not created and not self._user_repository.verify_login(username, password):
            return None

        return self._user_repository.get_rating(username)

    async def _handle_message(
        self, match: _Match, connection: ServerConnection, assigned_color: Optional[Color], message: object
    ) -> None:
        """Parse one raw incoming message and dispatch it to the
        matching handler - see module docstring's "JUMP COMMAND
        ROUTING AND REJECTION SCHEME" section for why this can never
        misroute a genuine move command.

        Args:
            match: The real _Match this connection belongs to.
            connection: The connection `message` arrived on.
            assigned_color: The color this connection was assigned when
                matched, or None if this connection is a VIEWER (Stage
                F5 - see module docstring's "STAGE F5" section and
                `_handle_move_command`'s own docstring for what a viewer
                sending a move/jump command actually experiences).
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
        self, match: _Match, connection: ServerConnection, assigned_color: Optional[Color], parsed: ParsedMoveCommand
    ) -> None:
        """Validate and dispatch one ALREADY-PARSED move command - see
        module docstring's "MOVE COMMAND REJECTION SCHEME" for the
        exact rejection responses this sends.

        STAGE F5 - A VIEWER'S MOVE IS REJECTED BY THIS SAME wrong_color
        CHECK, WITH NO NEW BRANCH: `assigned_color` is None for a viewer
        (see module docstring's "STAGE F5" section) - `parsed.color` is
        always a real, parsed Color, never None, so
        `parsed.color is not assigned_color` is unconditionally True for
        a viewer regardless of which color it claims, rejecting with the
        exact same "rejected:wrong_color" wire text a real player's own
        wrong-color attempt already produces. This is
        Implementation_Plan.md's own "a third value on an existing
        mechanism, not a new one" made literal - no viewer-specific
        `if` was added anywhere in this method."""

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
        self, match: _Match, connection: ServerConnection, assigned_color: Optional[Color], parsed: ParsedJumpCommand
    ) -> None:
        """Validate and dispatch one ALREADY-PARSED jump command - see
        module docstring's "JUMP COMMAND ROUTING AND REJECTION SCHEME"
        for the exact rejection responses this sends - see
        `_handle_move_command`'s own docstring for why a viewer
        (`assigned_color is None`) is rejected by this SAME
        `wrong_color` check, with no new branch."""

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
        players AND any viewers currently watching (Stage F5 - see
        module docstring's "STAGE F5" section for why this is the ONE,
        minimal fan-out change this stage makes, not the broader F6
        audit), never every connection on the server."""

        connections: Tuple[ServerConnection, ...] = tuple(match.colors.keys()) + tuple(match.viewer_connections)
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
