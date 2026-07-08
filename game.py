"""
GameState: selection, game clock, click/wait/jump handling, and
time-delayed move + jump resolution.

Moves are scheduled with an arrival time (current clock + distance *
per-cell duration). Jumps put a piece "airborne" for JUMP_DURATION_MS:
the piece stays on its cell, but is treated specially if an enemy move
arrives there before the jump ends (see _settle_single_move).

Both pending moves and pending jump-landings are timestamped events;
they are processed together in strict chronological order so that
"did the jump end before or after the enemy arrived" is resolved
correctly.
"""

from constants import (
    EMPTY_TOKEN,
    CELL_SIZE,
    MOVE_DURATION_PER_CELL_MS,
    JUMP_DURATION_MS,
)
from pieces import is_legal_move, path_cells, SLIDING_PIECES


class GameState:
    def __init__(self, board):
        self.board = board
        self.selected = None      # (row, col) of the currently selected piece
        self.clock_ms = 0         # accumulated game clock
        self.pending_moves = []   # list of dicts: arrival/from/to/piece
        self.airborne = []        # list of dicts: cell/land_time/piece
        self.game_over = False    # set True once a king is captured

    @staticmethod
    def pixel_to_cell(x, y):
        col = x // CELL_SIZE
        row = y // CELL_SIZE
        return row, col

    # ------------------------------------------------------------------
    # Click (select / move request)
    # ------------------------------------------------------------------
    def handle_click(self, x, y):
        if self.game_over:
            return  # the game has ended; all further move commands are ignored

        self._process_due_events()

        row, col = self.pixel_to_cell(x, y)

        if not self.board.in_bounds(row, col):
            return  # clicking outside the board is ignored

        token = self.board.get(row, col)

        if self.selected is None:
            if (
                token != EMPTY_TOKEN
                and not self._has_pending_move_from(row, col)
                and not self._is_airborne(row, col)
            ):
                self.selected = (row, col)
            # clicking an empty cell, a piece mid-move, or an airborne
            # piece, with no current selection, is ignored
            return

        sel_row, sel_col = self.selected
        sel_token = self.board.get(sel_row, sel_col)
        sel_color = sel_token[0]

        if token != EMPTY_TOKEN and token[0] == sel_color:
            # clicking another friendly piece replaces the selection -
            # unless that piece is already moving or airborne, in which
            # case it cannot be (re)selected, so the click is ignored
            # and the current selection is kept.
            if not self._has_pending_move_from(row, col) and not self._is_airborne(row, col):
                self.selected = (row, col)
            return

        # clicking any other cell sends a move request from selected -> target
        if self._is_move_allowed(sel_row, sel_col, row, col) and \
                not self._opposing_color_move_in_flight(sel_color):
            if token != EMPTY_TOKEN and token[1] == "K" and not self._is_airborne(row, col):
                # Capturing the enemy king is instant (no transit delay) -
                # the game ends immediately, UNLESS the king is currently
                # airborne (jump-protected), in which case it's queued
                # normally and subject to the jump-interception rules.
                self.board.set(row, col, sel_token)
                self.board.set(sel_row, sel_col, EMPTY_TOKEN)
                self.game_over = True
            else:
                self._schedule_move(sel_row, sel_col, row, col)
        # Illegal / rejected moves are ignored: the board is left unchanged.
        self.selected = None

    # ------------------------------------------------------------------
    # Jump
    # ------------------------------------------------------------------
    def handle_jump(self, x, y):
        if self.game_over:
            return

        self._process_due_events()

        row, col = self.pixel_to_cell(x, y)

        if not self.board.in_bounds(row, col):
            return  # jumping outside the board is ignored

        token = self.board.get(row, col)
        if token == EMPTY_TOKEN:
            return  # nothing to jump (also covers "a captured piece can't jump")

        if self._has_pending_move_from(row, col):
            return  # rule: a moving piece cannot jump

        if self._is_airborne(row, col):
            return  # already jumping; ignore a redundant jump request

        land_time = self.clock_ms + JUMP_DURATION_MS
        self.airborne.append({
            "cell": (row, col),
            "start_time": self.clock_ms,
            "land_time": land_time,
            "piece": token,
        })

    def _is_airborne(self, row, col):
        return any(a["cell"] == (row, col) for a in self.airborne)

    # ------------------------------------------------------------------
    # Move legality
    # ------------------------------------------------------------------
    def _pawn_start_row(self, color):
        """
        The row a color's pawns begin on: white starts on the bottom-most
        row of the board, black starts on the top-most row (confirmed by
        test evidence - not the "one row in" convention of standard chess).
        """
        if color == "w":
            return self.board.num_rows - 1
        return 0

    def _is_move_allowed(self, from_row, from_col, to_row, to_col):
        sel_token = self.board.get(from_row, from_col)
        sel_color = sel_token[0]
        piece_letter = sel_token[1]

        dest_token = self.board.get(to_row, to_col)

        # 1) Cannot capture a piece of the same color.
        if dest_token != EMPTY_TOKEN and dest_token[0] == sel_color:
            return False

        is_capture = dest_token != EMPTY_TOKEN
        is_start_row = piece_letter == "P" and from_row == self._pawn_start_row(sel_color)

        # 2) Shape must match the piece's movement pattern (pawn's shape
        #    rules also depend on color, capture status, and whether it's
        #    moving from its start row - which permits a 2-cell move).
        if not is_legal_move(
            piece_letter, from_row, from_col, to_row, to_col, sel_color, is_capture, is_start_row
        ):
            return False

        # 3) Sliding pieces (rook/bishop/queen) cannot jump over blockers,
        #    and neither can a pawn's 2-cell opening move.
        needs_path_check = piece_letter in SLIDING_PIECES or (
            piece_letter == "P" and abs(to_row - from_row) == 2
        )
        if needs_path_check:
            for (r, c) in path_cells(from_row, from_col, to_row, to_col):
                if self.board.get(r, c) != EMPTY_TOKEN:
                    return False

        return True

    def _has_pending_move_from(self, row, col):
        """True if the given cell is currently the origin of an unsettled
        (in-flight) move - i.e. the piece there cannot be redirected."""
        return any(m["from"] == (row, col) for m in self.pending_moves)

    def _opposing_color_move_in_flight(self, mover_color):
        """True if any currently in-flight move belongs to the opposite
        color - such a move request must be rejected outright."""
        return any(m["piece"][0] != mover_color for m in self.pending_moves)

    def _schedule_move(self, from_row, from_col, to_row, to_col):
        """
        Register a move request to settle later, instead of applying it
        immediately. Duration scales with distance traveled (in cells):
        duration = max(|dr|, |dc|) * MOVE_DURATION_PER_CELL_MS.
        """
        piece = self.board.get(from_row, from_col)
        distance = max(abs(to_row - from_row), abs(to_col - from_col))
        duration = distance * MOVE_DURATION_PER_CELL_MS
        arrival = self.clock_ms + duration
        self.pending_moves.append({
            "arrival": arrival,
            "requested_at": self.clock_ms,
            "from": (from_row, from_col),
            "to": (to_row, to_col),
            "piece": piece,
        })

    # ------------------------------------------------------------------
    # Promotion
    # ------------------------------------------------------------------
    def _promotion_row(self, color):
        """The last row a pawn of this color reaches: row 0 for white
        (moving upward), the bottom row for black (moving downward)."""
        if color == "w":
            return 0
        return self.board.num_rows - 1

    def _apply_promotion_if_needed(self, row, col):
        token = self.board.get(row, col)
        if token == EMPTY_TOKEN:
            return
        color, letter = token[0], token[1]
        if letter == "P" and row == self._promotion_row(color):
            self.board.set(row, col, color + "Q")

    # ------------------------------------------------------------------
    # Chronological event settlement (moves settling + jumps landing)
    # ------------------------------------------------------------------
    def _process_due_events(self):
        """
        Gather every pending move whose arrival has passed and every
        airborne jump whose landing time has passed, and process them
        together in strict chronological order (ties broken with
        landings first - see _land_jump for why this matters).
        """
        events = []
        for m in self.pending_moves:
            if m["arrival"] <= self.clock_ms:
                events.append((m["arrival"], 0, "move", m))
        for j in self.airborne:
            if j["land_time"] <= self.clock_ms:
                events.append((j["land_time"], 1, "land", j))

        events.sort(key=lambda e: (e[0], e[1]))

        for _time, _priority, kind, obj in events:
            if kind == "land":
                self._land_jump(obj)
            else:
                # The move may already have been intercepted and removed
                # by a "land" event processed earlier in this same batch.
                if obj in self.pending_moves:
                    self._settle_single_move(obj)
                    self.pending_moves.remove(obj)

    def _land_jump(self, jump):
        """
        A jump lands. Before simply landing safely, check whether an
        enemy piece committed to a move targeting this cell WHILE the
        piece was airborne (requested_at >= this jump's start_time).
        If so, that attacker is captured/destroyed right now, regardless
        of its own arrival time - it "flew into" a defended cell. A move
        requested BEFORE this jump began is NOT intercepted; it resolves
        normally whenever it naturally arrives (see _settle_single_move).
        """
        cell = jump["cell"]
        jump_color = jump["piece"][0]
        start_time = jump["start_time"]

        for m in self.pending_moves:
            if (
                m["to"] == cell
                and m["piece"][0] != jump_color
                and m["requested_at"] >= start_time
            ):
                from_row, from_col = m["from"]
                self.board.set(from_row, from_col, EMPTY_TOKEN)
                self.pending_moves.remove(m)
                break  # only one piece can occupy/target a cell at a time

        self.airborne.remove(jump)

    def _settle_single_move(self, move):
        from_row, from_col = move["from"]
        to_row, to_col = move["to"]

        # Re-validate against the CURRENT board state - other events may
        # have changed it since this move was requested (blockers,
        # friendly-piece landing, etc; see prior iteration's docstring).
        if not self._is_move_allowed(from_row, from_col, to_row, to_col):
            return  # the move fails silently - the piece stays at its origin

        if self._is_airborne(to_row, to_col):
            # Air capture: the destination piece is currently jumping and
            # defends itself - the ARRIVING piece is destroyed instead.
            # The airborne piece stays exactly where it is; the mover is
            # simply removed (not left at its origin - it was captured).
            self.board.set(from_row, from_col, EMPTY_TOKEN)
            return

        captured_token = self.board.get(to_row, to_col)
        self.board.set(to_row, to_col, move["piece"])
        self.board.set(from_row, from_col, EMPTY_TOKEN)
        if captured_token != EMPTY_TOKEN and captured_token[1] == "K":
            self.game_over = True
        self._apply_promotion_if_needed(to_row, to_col)

    # ------------------------------------------------------------------
    # Wait / print
    # ------------------------------------------------------------------
    def handle_wait(self, ms):
        self.clock_ms += ms
        self._process_due_events()

    def print_board(self):
        # Settle first so print always reflects the current clock time,
        # even if called without an intervening wait.
        self._process_due_events()
        print(self.board.to_canonical_string())