# Kung Fu Chess — Personal Specification Document

## 1. General Development Rules

Every development step follows this loop:

Requirements -> Test planning -> Writing tests -> Code implementation ->
Refactoring -> AI review -> Peer review -> Commit to Git.

**Rules:**
- Game logic is separate from the UI.
- Unit tests for logic must be written before wiring to the UI.
- Tests use logical/simulated time, not real waiting.
- The rendering engine is thin and easily replaceable.
- No hidden global state.
- Use small classes with separated responsibilities — each class has a
  single clear responsibility.
- Commit only after tests pass.
- Add a short textual explanation for every non-trivial implementation
  decision.

**Rules for using AI:**
- Ask focused questions, not broad/general ones.
- The LLM does not replace the design done by the developer — it may
  improve and add, but it does not design on its own.
- Debugging rules with AI:
  - Submit to the AI: the planning steps, expected behavior, current
    behavior, and only the relevant portion of the code or test.
  - Before requesting a fix, the developer must check which layer is
    responsible for the issue.
  - Make the smallest possible change needed to make the specific test
    pass.
  - Ask, for every change, why it is required!
  - After getting an answer, instruct the LLM to perform a REVIEW on
    itself.

## 2. Scope of the Game

**Shared game rules:**
- The board can be any rectangular shape — its size is inferred from a
  textual description.
- Pieces are described using standard chess letters: K, Q, R, B, N, P.
- Piece color is described in the format: wK, bR, etc.
- "." represents an empty square.
- The game does not implement check, checkmate, castling, promotion
  (in the standard sense), or en passant.
- A king can be captured.
- Capturing the opposing king ends the game.
- A piece moves only according to its own movement rules.
- Sliding pieces cannot move if blocked by pieces in their path.
- Movement has a fixed, constant speed.
- Tests use a fixed cell size in pixels.
- UI rendering uses only the drawing/image library supplied to it.
- The logical board changes only after a moving piece has actually
  reached its destination.
- There can only be one legal motion in progress at a time — if
  another request is received, the game engine rejects it with the
  message `motion_in_progress`.
- The integration test DSL contains exactly: `Board`, `click`, `wait`,
  `print board`.
- The `print board` method is the only integration test assertion
  mechanism.

**Additional optional future movement rules that the architecture must
support extending easily, without breaking the base logic:**
- Simultaneous movement of pieces at the same time.
- Cooldown after a move.
- Collision between moving pieces.
- Cancelling an action if the target is captured before arrival.
- Support for replayable script files.
- A basic bot strategy.
- Visual polish without changing the model.

## 3. Core Design Decision: Splitting the System into Runnable Layers

**Layers:**

| Layer | Contains | Does NOT contain |
|---|---|---|
| Model | board coordinates, piece identity, logical occupancy, piece lifecycle state | pixels, clicks, rendering, script parsing, movement rules, timing |
| MovementRules | movement geometry for each piece type, calculated from board and piece data | game commands, elapsed time, animation, click interpretation, game-over state |
| RuleEngine | read-only legality validation for a requested move | board mutation, animation, click interpretation, game-over state |
| GameEngine | Application service coordination: game-over guard, validation delegation, starting legal motions, wait delegation, snapshots | piece-specific movement logic, rendering, input parsing, DSL parsing, pixel mapping |
| RealTimeArbiter | active motion objects, simulated time advancement, arrival resolution, capture events | chess legality, clicks, rendering, script parsing |
| Controller | click interpretation and selected-cell state | chess legality, board mutation, rendering, timing |
| Renderer | visual drawing from a read-only GameSnapshot | game rules, board mutation, input parsing, text-test logic |
| TextTestRunner | script parsing and driving the public command path | movement rules, direct board mutation, duplicated game logic |
| Text I/O | BoardParser and BoardPrinter: textual setup and logical board output | movement rules, command execution, rendering, test assertion beyond text comparison |

## 4. Project Structure
KugFu_chess/
model/
position.py
piece.py
board.py
game_state.py
rules/
piece_rules.py
rule_engine.py
realtime/
motion.py
real_time_arbiter.py
input/
board_mapper.py
controller.py
io/
board_parser.py
board_printer.py
view/
renderer.py
image_view.py
texttests/
script_parser.py
script_runner.py
app.py
tests/
unit/
test_position.py
test_board.py
test_piece_rules.py
test_rule_engine.py
test_real_time_arbiter.py
test_game_engine.py
test_board_mapper.py
test_controller.py
test_board_parser.py
test_board_printer.py
integration/
scripts/
01_board_parsing.kfc
02_click_to_move.kfc
03_rook_moves.kfc
04_invalid_moves.kfc
05_capture.kfc
06_game_over.kfc
test_text_scripts.kfc

**Dependencies remain clean:**
- view depends on game-state snapshots
- controller depends on BoardMapper & GameEngine
- GameEngine depends on Board, RuleEngine, RealTimeArbiter
- RuleEngine depends on Board & PieceRules
- PieceRules depends on Board & Position data
- BoardParser & BoardPrinter depend on model data, but not on
  controller, RuleEngine, RealTimeArbiter, or Renderer
- TextTestRunner depends on BoardParser, BoardPrinter, Controller,
  GameEngine
- Nothing ever points from Model to UI!

**Pattern vocabulary:**

| Component | Pattern name |
|---|---|
| GameEngine | Application service |
| RuleEngine | Validation service |
| PieceRules | Strategy per piece type |
| BoardMapper | Coordinate Adapter |
| Renderer | View Adapter |
| GameSnapshot | Read-only view model / DTO |
| TextTestsRunner | Command-script test harness |

## 5. Class Design

### 5.1 Position
Fields: `row: int`, `col: int`
Planned behavior: equality, readable representation, no board-bounds
checking inside Position.
Unit tests:
- Two Positions with the same row and col are equal.
- Two Positions with different row or col are not equal.
- Position objects produce a readable assertion failure.

### 5.2 Piece
Fields:
- `id`: unique stable ID
- `color`: white / black
- `kind`: king / queen / rook / bishop / knight / pawn
- `cell`: Position
- `state`: idle / moving / captured

IDs are assigned at creation time, in the constructor.

### 5.3 Board
Responsible for:
- Storing width and height
- Adding a piece
- Removing a piece
- Querying whether a piece occupies a cell
- Checking whether a cell is within valid bounds
- Moving a piece, after it has been validated that this is a legal
  action
- Rejecting double occupancy of a cell

Board does not call RuleEngine, and RuleEngine does not mutate Board.

Unit tests:
- Board dimensions are inferred correctly.
- Empty cells return no piece.
- Occupied cells return the correct piece.
- Adding two pieces to the same cell fails.
- Moving a piece updates source and destination.
- Removing a captured piece clears its cell.

## 6. Movement Rules Design

Each piece type has its own rules class under the following interface:
legal_destination(board, piece) -> set[Position]

The class returns the set of destinations based on the piece's
movement — but does not mutate the board itself.

Legality follows standard chess rules, with the pawn having variable
rules: white moves one row up only, black one row down only, captures
diagonally, cannot move 2 steps except its opening move, has no en
passant and no promotion.

**Implementation order:** Rook, Bishop, Queen, Knight, King, Pawn.

Unit tests:
- Rook moves across empty row and col.
- Rook stops before a friendly blocker.
- Rook captures an enemy blocker but doesn't pass it.
- Bishop moves diagonally and not straight.
- Queen combines rook and bishop movement.
- Knight jumps over blockers.
- King moves one cell only.
- Pawn moves and captures according to the simplified pawn rules.

## 8. RuleEngine Design

Answers the question: given a target row and column, is the action
legal right now?

Responsible for:
- Rejecting a move outside the board area
- Rejecting moves from empty cells
- Rejecting a move toward a cell occupied by a friendly piece
- Requesting execution of the relevant step, if it is legal
- Returning a clear validation result

Response shape — fields:
MoveValidation:

is_valid: bool
reason: string


The reason for a valid result is `"ok"`. For an invalid result:
`"outside_board"`, `"empty_source"`, `"friendly_destination"`,
`"illegal_piece_move"`.

The RuleEngine is READ_ONLY — it does not change anything on the
board.

The DSL does not surface these reasons, but the UNIT TESTS do.

## 9. GameEngine Design

Answers the following questions:
- Has the game already ended (GAME OVER)?
- Is another motion currently still active on this track?
- Does the move request need to go to the RULE ENGINE for legality
  checking?
- Does a legal move need to start a track through the REAL TIME
  ARBITER?
- Does simulated time need to advance through the REAL TIME ARBITER?
- Which READ-ONLY GAMESNAPSHOTS need to be exposed to the renderer?

Responsible for:
- Holding or pointing to the current game state, including a
  `game_over` flag.
- Rejecting a request when `game_over` is true, returning:
  `MoveResult(reason='game_over')`.
- Rejecting a request when there is still an active motion on the
  current track, returning: `MoveResult(reason='motion_in_progress')`.
- Calling `RULEENGINE.VALIDATE_MOVE` only after application-level
  checks pass.
- Starting a legal motion through the REAL TIME ARBITER.
- Delegating `wait(ms)` to `RealTimeArbiter.advance_time(ms)`.
- Receiving notice that the king has been captured and setting the
  `GAME_OVER` flag to `TRUE`.
- Creating GAMESNAPSHOTS for the RENDERER and the BOARDPRINTER.

Fields:
- `is_accepted: bool`
- `reason: string`

## 10. Real-Time Movement Design: RealTimeArbiter

Accepts only move commands whose legality has already been checked.
Active motions are stored outside the board. RealTimeArbiter holds a
COLLECTION of active motion objects.

**Constants:**
- `CELL_SIZE = 100 pixels`
- `PIECE_SPEED = 100 pixels per second`

**Time is deterministic:**
- A move of one square takes 1000 MS.
- A move of 2 squares takes 2000 MS.
- A move of N squares takes `N * 1000 MS`.
- Diagonal movement is measured by number of squares, not Euclidean
  distance.

**Board update logic:**
The board changes only after the piece has actually reached its
destination — this lets the renderer draw positions from SNAPSHOTS
while always keeping the board legal. This makes `PRINT BOARD`
deterministic:
- Before arrival — shows the old board.
- After arrival — shows the updated board.

This way, the piece can be drawn mid-transit between cells while
keeping the board legal at all times.

**Arrival rules:**
When a piece reaches its destination:
- It is removed from the source cell.
- Any piece occupying the destination cell is captured, if present.
- The piece is placed in the destination cell.
- If the piece in the destination cell is a king, the king capture
  must be reported to the GAMEENGINE.

Tests do not call real "sleep." In the engine, the action is:
`engine.wait(ms)`, and the TEXTTESTCOMMAND calls this function.

## 11. Controller Design

Responsible for:
- Receiving click coordinates
- Converting pixels to board cells via BOARDMAPPER
- Maintaining selected-piece state — SELECTED_PIECE
- Single click — selecting a piece
- Double click — calling `GameEngine.request_move(source, destination)`
- Clearing the selection after every double click of an IN_BOARD
  CLICK — whether legal or not
- If nothing is selected — rejecting clicks outside the board
- If a piece is selected — a click outside the board cancels the
  selection and does not send a command to GameEngine
- Ignoring a single click on an empty cell

The Controller must NOT call piece movement directly, and must NOT
call the RULE ENGINE directly.

**`pixel_to_cell` mapping:**
- `col = x // 100`
- `row = y // 100`

**Camera / Viewport decision:**
The shared track has no scrolling camera. VIEWPORT SUPPORT belongs
only to the EXTRA track — if it is added, the mapping will be done
inside BOARDMAPPER and not inside the model.

## 12. View / Renderer Design

The VIEW draws the game's progress — it does not have the game rules
and does not change the board.

Responsible for the RENDERER:
- Drawing the board GRID
- Drawing pieces at pixel positions
- Highlighting a selected piece
- Drawing motion between cells
- Displaying a GAME OVER message

The RENDERER receives a READ_ONLY SNAPSHOT:
GameSnapshot:

board_width
board_height
pieces with kind / color / pixel position / state
game_over flag


Tests for the VIEW remain minimal.

## 13. Text-Based Integration Test Language

**Required commands:**
The DSL contains exactly 4 commands:
- `Board` <textual board rows>
- `click <x> <y>`
- `wait <milliseconds>`
- `print board`

**Board notation rules:**
- Each row is written on a separate line.
- Cells are separated by spaces.
- "." marks an empty cell.
- White pieces start with `w`.
- Black pieces start with `b`.
- Piece kinds are marked with: `K Q R B N P`.
- Board width and height are inferred from the text.
- Every row must have the same number of cells.

## 14. Minimal Assertion Strategy

The INTEGRATION TESTS use only:
print board
<expected board rows>

This covers all common possible paths:
- BOARD PARSING is tested by printing the current board.
- Pixel mapping is tested by clicking a piece and observing the
  resulting board after the move.
- A legal move is tested by observing the piece at the destination
  after enough time has passed.
- Separate real-time motion is tested by printing before and after
  the motion.
- An illegal move is tested by printing the board with no change.
- Blocking is tested by printing the board with no change after
  attempting a blocked step.
- Capture is tested by printing the board where the captured piece
  has disappeared.
- King capture and game end are tested by sending another legal move
  after the king has been captured, and printing the board with no
  change.

## 15. How Text Tests Connect to the Implementation

Does not duplicate the logic. It performs the same actions a user
would perform. It also has no board printing/conversion rules of its
own: this responsibility is delegated to the shared TEXT I/O ADAPTERS.
Board text -> BoardParser -> GameEngine initial state
click -> Controller.click(x, y)
wait -> GameEngine.wait(ms)
print board -> BoardPrinter.print(game_state)

**The flow:**
Script runner parses commands, calls Controller for click, calls
GameEngine for wait, calls BoardPrinter for print board, compares
expected output.

## 16. Unit Test Layers

UNIT TESTS answer the question: is this component isolated?
INTEGRATION TESTS answer the question: does the feature work from the
outside?
