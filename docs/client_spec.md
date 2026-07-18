# Kung Fu Chess — Client Layer Specification (View / Input)

Version 1 · Draft for discussion · Builds directly on the existing
`docs/spec.md` (logic layer) + CTD26 asset guidelines (Img class only)

## 0. Purpose and Background

This document defines the requirements and architecture of the client
layer (real graphical View + Input) for the Kung Fu Chess project, as
a direct continuation of the existing, already-implemented and tested
logic layer (model / rules / engine / realtime).

**Hard constraint:** all graphics (board, pieces, animations, score,
move log) must go exclusively through the given `Img` class (built on
OpenCV). No pygame / SFML / LWJGL or any other ready-made game/UI
library may be used. This means there is no ready-made game loop,
event loop, or mouse handling — all of it must be designed and built
from scratch.

## 1. Guiding Principles

The new architecture continues the baseline already established in
the logic spec, and explicitly applies SOLID to it:

- **SRP** (single responsibility): every new class does exactly one
  thing — `ImgSurface` only draws, `ScreenToImageMapper` only converts
  coordinates, `PieceAnimator` only manages animation state,
  `ScoreObserver` only computes score.
- **OCP** (open/closed): adding a new Observer type, a new animation
  state, or a new Surface implementation (e.g. a future Web client)
  must not require changing existing code — only adding to it.
- **LSP** (safe substitution): any `Surface` implementation
  (`RecordingSurface` for tests, `ImgSurface` for production) is
  freely interchangeable behind the same contract — exactly as already
  happens today in the logic layer.
- **ISP** (focused interfaces): there is no single "fat" interface.
  `Surface` (board drawing), `Observer` (event reception), and
  `AnimationProvider` (frame supply) are three separate, small
  contracts.
- **DIP** (depend on abstractions): `GameLoopRunner`, `Renderer`, and
  `HudRenderer` depend only on protocols (`Surface`, `Observer`,
  `GameSnapshot`) — never on concrete implementations. Wiring (who is
  injected into whom) happens in exactly one place, like
  `app_extra.py` today.

**Additional iron rule**, continuing `spec.md`: *"never points from
model to UI."* All new dependencies flow from `client` toward
`view`/`engine`/`model`, never the other way. The client layer never
mutates `board` / `piece` / `game_state` directly — it only reads them
through snapshots.

## 2. Proposed Directory Structure

In addition to code, a new top-level assets directory is added,
`assets/`, at the repo root — a **sibling** of `kungfu_chess/`, not
inside it (see rationale in §11):
`assets/pieces/<KIND><COLOR>/states/<state>/{config.json, sprites/}`,
and `assets/board.png`.

A new package `kungfu_chess/client/`, parallel in status to the
existing `view/` and depending on it (never the reverse):

```
kungfu_chess/client/
    surface/
        img_surface.py       # Surface implementation on top of Img
        asset_cache.py       # image/sprite loading + caching
    animation/
        animation_state.py   # Enum of animation states
        state_config.py      # StateConfig dataclass + config.json loading
        piece_animator.py    # per-piece animation state machine
    input/
        screen_mapper.py     # ScreenToImageMapper (pure, testable)
        mouse_adapter.py     # wraps cv2.setMouseCallback -> Controller
    events/
        game_events.py       # event type definitions (dataclasses)
        event_publisher.py   # Subject: publishes events from GameEngine
        observers.py         # Observer Protocol + MovesLogObserver + ScoreObserver
    ui/
        score_table.py       # PIECE_VALUES table
        hud_renderer.py       # draws log / score / player names
    loop/
        game_loop.py          # GameLoopRunner: wires everything together

tests/unit/client/            # unit tests mirroring every component above
```

## 3. Component / Responsibility Table

| Component | Responsibility | Depends on |
|---|---|---|
| `ImgSurface` | Implements `Surface` on top of `Img`; draws grid, pieces, highlights, HUD | `Img`, `Surface` protocol |
| `AssetCache` | Loads and caches sprites/images from `assets/` | filesystem, `Img` |
| `AnimationState` | Enum of the 5 animation states | — |
| `StateConfig` | Dataclass + loader for a single state's `config.json` | filesystem |
| `PieceAnimator` | Per-piece animation state machine; advances frames by `delta_ms`; reacts to events | `AnimationState`, `StateConfig`, `Observer` |
| `ScreenToImageMapper` | Pure conversion: window pixel → logical image pixel | none (pure) |
| `MouseAdapter` | Thin wrapper over `cv2.setMouseCallback`; calls mapper then `Controller.click` | `ScreenToImageMapper`, `Controller` (existing, unchanged) |
| `GameEventPublisher` | Decorator around `GameEngine`; turns its outputs into published events | `GameEngine` (existing, unchanged) |
| `Observer` (protocol) | Single method `on_event(event)` | — |
| `MovesLogObserver` | Builds a read-only `MovesLogSnapshot` from events | `Observer` |
| `ScoreObserver` | Builds a read-only `ScoreSnapshot` from events, using `PIECE_VALUES` | `Observer`, `score_table` |
| `HudRenderer` | Draws log/score/player names onto the canvas, from snapshots only | `Img`, `MovesLogSnapshot`, `ScoreSnapshot` |
| `GameLoopRunner` | The only high-level component that knows all the others; the composition root | all of the above |

`HudRenderer` depends on `Img` directly, not on the `Surface` protocol:
`Surface` (`kungfu_chess/view/image_view.py`) is a fixed contract
shared with the logic layer's own tests (`RecordingSurface`), and
extending it with HUD-specific methods would leak a client-only
concern into a cross-layer contract that doesn't need it - `Img`
already provides everything `HudRenderer` needs (Stage 6).

`GameLoopRunner` is the sole component at the top level that is aware
of every other component — exactly like `app_extra.py` in the logic
layer, which is the single wiring location. Every other class knows
only what it needs (ISP + DIP).

## 4. Game Loop — Execution Flow

A real-time loop (~30 FPS, see rationale in §8) replacing the DSL used
for tests (the DSL keeps existing in parallel, purely for tests!):

1. Measure elapsed time (`delta_ms`) since the previous frame using a
   real system clock.
2. Call `GameEventPublisher.wait(delta_ms)` (wraps
   `GameEngine.wait`) — logical time advances, `ArrivalEvent` /
   `CancellationEvent` / `CollisionEvent` are produced and published
   to Observers.
3. Update every active `PieceAnimator` by `delta_ms` (advance frame /
   check animation completion / transition state).
4. `build_snapshot(engine, controller)` — build a pure, unchanged
   `GameSnapshot`, exactly as it already exists today.
5. `Renderer.render(snapshot)` draws the board onto an `Img` canvas
   via `ImgSurface`.
6. `HudRenderer` draws the move log, score, and player names onto the
   same canvas (or a secondary canvas that gets merged), from separate
   read-only snapshots (`MovesLogSnapshot`, `ScoreSnapshot`) built from
   the Observers.
7. `Surface.show()` — display the composed frame (`cv2.imshow`).
8. `MouseAdapter` handles clicks asynchronously (callback), converting
   them to `Controller.click` calls via `ScreenToImageMapper`.
9. Return to step 1, until `game_over` or window close.

## 5. Animation State Machine

Based precisely on the `config.json` structure found under
`CTD26/pieces2/<KIND><COLOR>/states/<state>/`. Five fixed states, each
with `sprites/` and a `config.json` (physics: `speed_m_per_sec` +
`next_state_when_finished`; graphics: `frames_per_sec` + `is_loop`).

`PieceAnimator` is an `Observer` of `GameEventPublisher`: it does not
need to check every frame "did this piece start moving" — it
transitions directly into the `move` state upon receiving a
`MoveAccepted` event for its own `piece_id`. This is exactly where the
Observer also serves rendering itself (not just log/score).

**Decision on `jump`:** the `jump` state is not purely visual — it is
tied directly to the existing logic in `extra/jump.py`, currently run
through `ExtraEngine`. It is expected that `jump` will later be merged
into the core logic (no longer a separate extra). Implication for
`PieceAnimator`: the transition to the `JUMP` state must be driven by
a dedicated event (`JumpAccepted`, parallel to `MoveAccepted`) coming
from the actual `ExtraEngine`/`GameEngine`, not inferred visually —
so the animation always reflects the true logical source, both before
and after `jump` is unified into the core.

## 6. Observer / Events

`GameEventPublisher` wraps `GameEngine` (Decorator, not a
modification) and publishes events defined as frozen, read-only
dataclasses:

- `MoveRequested(from_cell, to_cell, piece_id)`
- `MoveAccepted(piece_id, from_cell, to_cell, duration_ms)`
- `JumpAccepted(piece_id, from_cell, to_cell, duration_ms)` — source:
  `ExtraEngine` (`extra/jump.py`); to later be unified into a single
  source with `GameEngine`
- `MoveRejected(reason)`
- `PieceArrived(piece_id, cell, captured_piece_id | None)`
- `GameOver(winner_color)`

The `Observer` protocol is deliberately minimal (ISP): a single method
`on_event(event)`. Each consumer (`MovesLogObserver`, `ScoreObserver`,
`PieceAnimator`) picks which event types it cares about and ignores
the rest — adding a new consumer type (OCP) touches neither
`GameEventPublisher` nor the existing consumers.

`MovesLogObserver` and `ScoreObserver` build their own read-only data
structures in response to events (`MovesLogSnapshot`, `ScoreSnapshot`)
— the same pattern as the existing `build_snapshot` for
`GameSnapshot` — so that `HudRenderer` continues to depend only on
snapshots, never on the Observer itself.

## 7. Screen ↔ Image Pixel Mapping

Required because of relative window location and dynamic window size:
a raw mouse coordinate from the window is not the same as a pixel
coordinate inside the logical board image.

`ScreenToImageMapper` is a pure class (no dependency on `cv2` / an
actual window): given `window_origin` (x, y) and `window_scale`, it
returns a `Position` via `image_x = (screen_x - origin_x) / scale`
(and similarly for y). Because it is pure, it can be unit-tested
without ever opening a graphical window — see §9.

`MouseAdapter` is the thin layer that actually sits on top of
`cv2.setMouseCallback`, calls `ScreenToImageMapper`, and finally calls
the existing `Controller.click(x, y)` — unchanged.

Note: this is a separate concern from the existing `BoardMapper`
(pixel → logical cell, `col = x // CELL_SIZE`). `ScreenToImageMapper`
sits one layer above it, converting *window* coordinates to *image*
coordinates before `BoardMapper` ever runs.

## 8. FPS and Loop Pacing

The highest FPS found in the given configs is `frames_per_sec=12`
(move state). A 30 FPS game loop is recommended: comfortable margin
(2.5x) above the fastest animation rate, without over-rendering full
frames too frequently through OpenCV (which is not built for
GPU-accelerated high-frequency rendering). Can be recalibrated later
if lag is observed.

## 9. Testing Strategy

Directly continuing the existing principle "unit tests before wiring
to UI":

- **`ScreenToImageMapper`**: pure unit test — known input
  `(screen_x, screen_y, window_origin, scale)`, expected `Position`
  output. Includes edge cases: click on a cell boundary, click outside
  the board, changing scale/origin.
- **`PieceAnimator`**: unit test with simulated logical time (exactly
  like `RealTimeArbiter`) — inject events, assert state transitions
  and frame index, no graphical window involved.
- **`MovesLogObserver` / `ScoreObserver`**: unit test — inject a
  simulated event sequence, assert the final snapshot.
- **`ImgSurface`**: a narrow test that checks drawing calls happen
  (e.g. via a fake/spy `Img`), not the actual visual output.
- **Manual/semi-manual check** ("how to test yourself"): a dev-only
  script that draws a circle/mark on whatever cell was resolved from a
  real click at runtime — a one-time visual confirmation that mapping
  is correct in practice, in addition to the pure automated test.

## 10. Open Questions / Working Assumptions

- **Working assumption (easy to change):** handling multiple
  same-tick piece events is done in the order received from
  `GameEngine`/`ExtraEngine` (FIFO, no extra sorting), with no
  assumption of dependency between different `piece_id`s.
  `GameEventPublisher` does not sort/prioritize events itself — it
  only forwards them as received. For two conflicting events for the
  same `piece_id` in the same tick (e.g. `MoveAccepted` followed by a
  `CancellationEvent`), `PieceAnimator` applies "last event wins" by
  arrival order. To keep this assumption easy to change: the
  processing order is not hardcoded inside `GameLoopRunner`, but goes
  through a single, focused policy function —
  `EventOrderingPolicy(events) -> events` — whose default is identity
  (FIFO as received), replaceable by injection (DIP) with a different
  policy (event-type priority, sort by `piece_id`, etc.) without
  touching `GameLoopRunner`, the Observers, or `PieceAnimator`
  themselves. A unit test must simulate several pieces
  moving/being-captured/cancelling in the same tick and verify that
  each Animator reacts only to events carrying its own `piece_id`.
- **Assumption:** default FPS = 30, calibratable (approved as a design
  judgment call).
- **Open:** the client work order is not sequential like the logic
  layer's section numbers — it will be defined by dependencies (see
  correspondence), not by section numbers.
- **Decided:** `jump` is linked to the existing `extra/jump.py` logic
  (currently via `ExtraEngine`), see §5. `GameEventPublisher` must
  expose a `JumpAccepted` event separate from `MoveAccepted`.
- **Documented, accepted gap:** `state_config.py`'s `_require` does not
  validate that `frames_per_sec > 0`. A `frames_per_sec` of `0` does
  not crash anything (`PieceAnimator.advance()`'s `frames_elapsed`
  stays `0` forever), but silently "freezes" that state's animation on
  frame 0 instead of erroring. A real vendored asset would never have
  this, so it is left as a documented, accepted gap rather than an
  urgent fix.
- **Documented, accepted gap:** `Img.paste()`
  (`kungfu_chess/client/surface/img.py`) assumes every sprite has
  either 3 (BGR) or 4 (BGRA) channels. A genuinely single-channel/
  grayscale sprite would raise a bare `IndexError` from
  `sprite._array.shape[2]` instead of a named `ImgSurfaceError`
  subclass. All real vendored assets (Stage 1) are confirmed RGBA, so
  this is a documented, accepted gap, not an urgent fix - same
  treatment as the `frames_per_sec=0` gap above.
- **Documented, accepted gap:** `HudRenderer`'s fixed top-left text
  position (Stage 9) currently overlaps the board's own top-left
  corner cells when both are drawn on the same canvas (Stage 10's
  `GameLoopRunner` sizes the canvas to exactly `board.width/height *
  CELL_SIZE`, with no extra HUD margin). This is COSMETIC ONLY -
  gameplay is unaffected, since `ImgSurface`/`Renderer` and
  `HudRenderer` still each draw correctly, just into the same pixel
  region. A future improvement could give `HudRenderer` a configurable
  region or reserve a dedicated canvas strip, but that would mean
  changing `HudRenderer`'s already-merged fixed constants again - out
  of scope for Stage 10, so deferred rather than fixed silently or
  ignored outright.
- **Documented, accepted gap:** Stage 12's `CooldownTracker`
  (`kungfu_chess/client/events/cooldown_tracker.py`) only tracks the
  ordinary move-arrival cooldown (`COOLDOWN_MS`, via `PieceArrived`) -
  it does NOT track JUMP's own post-landing cooldown
  (`JUMP_COOLDOWN_MS`, `kungfu_chess/extra/jump.py`). Reason: JUMP
  landings are resolved entirely inside `JumpTracker.resolve_due`
  (called from `ExtraEngine.wait`), which currently publishes no
  client-visible event marking when a landing (and its cooldown)
  actually starts - there is nothing for a client-side tracker to
  react to. Closing this gap would require a future stage to add a new
  published event from `ExtraEngine`/`JumpTracker` for a jump landing,
  which is out of Stage 12's scope; until then, a piece that just
  landed from a JUMP shows no cooldown bar even though it is real and
  enforced by `GameEngine.request_move`'s own `cooldown_active` guard.

## 11. Integrating Animation Assets from the CTD26 Repo (Asset Import)

The `CTD26` repo (`https://github.com/KamaTechOrg/CTD26`) is an
**external data source only** (assets), not a code library the
project depends on. Practical conclusion: no permanent clone as a
dependency, and no importing it as-is — only the relevant *data* is
imported into this project's own repo.

**Why not a submodule / live dependency:** the CTD26 repo also
contains Java and C++ code irrelevant to this Python project, and two
alternative graphics sets (`pieces1/` and `pieces2/`, ~6MB and ~2MB
respectively) — no reason to drag all of that in as an
auto-updating dependency. The assets are static in nature
(images + config), not live code, so the clean approach is a one-time
copy ("vendoring") of only what is actually needed into our own repo,
version-controlled normally from then on.

**Where to place it — not inside `kungfu_chess/`:** the `assets/`
directory is placed at the repo root, a sibling of `kungfu_chess/`
(not inside it). Rationale: `kungfu_chess/` is an importable Python
code package, and binary assets (PNGs) don't conceptually belong
inside a code package — this also prevents bloating the
distributable/testable package, and is consistent with the existing
separation between code and pure logic ("never points from model to
UI" — the parallel here: code does not *contain* media data, it only
points to it via a defined path).

**Splitting required:** yes, on two counts:

1. Choosing a single graphics set (**decided: `pieces2`** — smaller
   (~2MB vs ~6MB for `pieces1`) and matches the `config.json` structure
   already verified in practice) — make sure `pieces1` is not
   accidentally dragged along during the copy step.
2. Stripping everything that isn't pure assets: `java/`, `cpp/`, `py/`
   directories (the Img sample code itself is already implemented /
   will be absorbed into `client/surface`, not kept as-is), and
   CTD26's internal docs/README.

Renaming from the generic `pieces1`/`pieces2` to `assets/pieces/` (a
name consistent with this project), while carefully preserving the
internal structure
`<KIND><COLOR>/states/<state>/{config.json, sprites/}` unchanged —
because `AnimationConfigLoader` will be written against this exact
structure.

**Proposed execution steps:**

1. Temporary clone (local work only, not a kept dependency) of
   `https://github.com/KamaTechOrg/CTD26.git`.
2. Verify that the chosen `pieces2` set fully satisfies the expected
   structure for every KIND+COLOR combination (12 combinations).
3. Copy `<pieces-set>/` → `assets/pieces/` and `board.png` →
   `assets/board.png` into the project repo (KF-Chess).
4. Add to git normally (a separate, focused commit: "Add animation
   assets from CTD26"), including a note of source/license in the
   commit message or a short `assets/README.md`.
5. Write `AnimationConfigLoader` against the `assets/pieces/` path
   using a single central constant/config (e.g. `ASSETS_ROOT`), not a
   path string scattered through the code — so the asset location/set
   can be swapped later without hunting for hardcoded paths (DIP).
6. Unit test `AnimationConfigLoader` against a small fixture subset of
   assets only (a small fixture inside `tests/`, not the full set) —
   so tests don't depend on the full asset volume.
