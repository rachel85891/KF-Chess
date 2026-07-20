"""EventBus: a generic, layer-agnostic publish/subscribe core.

This is a NEW, standalone package (`kungfu_chess/bus/`), a sibling of
model/rules/realtime/client, NOT nested inside any of them - see the
project's server-track background: the server needs one pub/sub
mechanism shared by game events, connection events, matchmaking
events, and room events alike, published and consumed by independent
parts of the system that must not depend on each other. This is
deliberately NOT the existing
`kungfu_chess/client/events/event_publisher.py` (`GameEventPublisher`):
that class is a narrow Decorator around one specific `GameEngine`,
converting ITS outputs into chess-specific events. `EventBus` knows
nothing about chess, the client layer, or any specific event's
meaning - a future stage can make `GameEventPublisher` (or a server-
side publisher) publish onto an `EventBus` instance, but `EventBus`
itself has zero dependency in that direction (OCP: adding a new event
type anywhere else later requires zero changes here).

DESIGN DECISION - exact type match only, no subclass/inheritance
matching: `publish(event)` looks handlers up by `type(event)` as a
plain dict key, not via `isinstance`. This is deliberate, not an
oversight: subclass-aware dispatch would force EventBus to define an
event type HIERARCHY (what subclasses what, and in which order
ambiguous multi-parent matches resolve) - exactly the kind of
event-shape opinion this class must NOT have (see module summary
above; "EventBus does not define or constrain event shapes"). Exact
matching keeps subscribe/publish a single, obvious dict lookup, and
lets every future event-type author decide their own subtyping
strategy (if any) without EventBus ever needing to change to
accommodate it.

DESIGN DECISION - no global/module-level singleton: EventBus is a
plain class with no shared class-level or module-level state; every
instance owns its own private `_handlers` dict, so two instances never
observe each other's subscriptions (see
test_two_independent_eventbus_instances_share_no_state). This matters
for the server use case described above: a future server process may
need one EventBus per room/game, each fully isolated, rather than one
process-wide bus every room's events funnel through.

DESIGN DECISION - handler exception policy is "isolate, then
re-raise": if a subscribed handler raises during `publish`, EventBus
still calls every OTHER handler subscribed to that event type (a
single misbehaving/unrelated subscriber - e.g. a buggy matchmaking
handler - must not silently stop an unrelated room handler from ever
receiving the event), but `publish` still raises the FIRST exception
it caught, once every handler has run, so the failure is never
silently swallowed - a caller (or a test) can still see and react to
the fact that some handler failed. Only the first exception is
raised, not all of them combined: turning N failures into one
faithfully-reported error would mean inventing a multi-exception
wrapper type this stage has no real caller for yet - see
test_only_the_first_of_several_raising_handlers_exceptions_propagates
for the exact, deterministic behavior this produces.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Type

Handler = Callable[[object], None]


class EventBus:
    """Routes published events to subscribed handlers, by exact event
    type - see this module's own docstring for the full reasoning
    behind every design decision below (exact-type matching, no
    singleton, isolate-then-reraise exception policy)."""

    def __init__(self) -> None:
        """Create a fresh, fully independent EventBus with no
        subscribers yet.

        Returns:
            None.
        """

        self._handlers: Dict[Type[object], List[Handler]] = {}

    def subscribe(self, event_type: Type[object], handler: Handler) -> None:
        """Register `handler` to be called with every future event of
        exactly `event_type` published on this bus.

        Args:
            event_type: The exact class of event to listen for (used
                as a plain dict key - see module docstring's "exact
                type match only" decision).
            handler: A callable taking a single event argument.
                Multiple independent handlers may be subscribed to the
                same event_type; all of them are called on publish, in
                the order they were subscribed (FIFO).

        Returns:
            None.
        """

        self._handlers.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type: Type[object], handler: Handler) -> None:
        """Remove a previously subscribed handler for `event_type`.

        Args:
            event_type: The event type `handler` was subscribed under.
            handler: The exact handler object to remove.

        Returns:
            None.

        Safe to call even if `handler` was never subscribed to
        `event_type` at all (or `event_type` has no subscribers
        whatsoever) - a deliberate no-op in both cases, not an error,
        since a caller unsubscribing defensively (e.g. during its own
        teardown) should never need to first check whether it was
        actually subscribed.
        """

        handlers = self._handlers.get(event_type)
        if not handlers:
            return
        try:
            handlers.remove(handler)
        except ValueError:
            pass

    def publish(self, event: object) -> None:
        """Deliver `event` to every handler subscribed to exactly
        `type(event)`, in subscription order.

        Args:
            event: A plain event object (any type - EventBus imposes
                no shape/base-class requirement on it).

        Returns:
            None.

        Raises:
            The first exception raised by any subscribed handler, if
            any did - see module docstring's "isolate, then re-raise"
            decision: every OTHER handler still runs regardless, this
            is raised only after all of them have.
        """

        handlers = self._handlers.get(type(event), [])

        # Iterate over a snapshot (list(...)), not the live list
        # itself - a handler that unsubscribes (itself or another
        # handler) mid-dispatch must not corrupt this loop's own
        # iteration over the subscriber list it's reading from.
        first_error: Exception | None = None
        for handler in list(handlers):
            try:
                handler(event)
            except Exception as exc:  # noqa: BLE001 - see policy above
                if first_error is None:
                    first_error = exc

        if first_error is not None:
            raise first_error
