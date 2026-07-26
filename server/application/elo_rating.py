"""elo_rating.py: Stage D3's own pure ELO rating computation - a
standalone module, no networking/persistence/GameSession knowledge at
all, mirroring server/application/matchmaking_queue.py's own "pure,
in-memory, no I/O" convention (see that module's own docstring for the
precedent this follows): every function here is a plain function of
plain ints, independently unit-testable without a real UserRepository/
GameServer/database of any kind.

WHY server/application/, NOT server/persistence/ ALONGSIDE
UserRepository: this module computes a NEW rating from two EXISTING
ones - it never reads or writes a database row, never constructs a
sqlite3 connection, and has no opinion about WHERE a rating came from
or WHERE it will be stored (server/application/game_server.py's own
new caller is the one that reads the old ratings via UserRepository.
get_rating and persists the new ones via UserRepository.update_rating -
see that class's own "STAGE D3" docstring section). This is the exact
same APPLICATION-vs-PERSISTENCE boundary server/persistence/
user_repository.py's own docstring already draws for itself ("a SQLite
row is not wire syntax" - applied here as "a rating FORMULA is not a
SQLite row" instead): a pure computation belongs in the APPLICATION
layer alongside the other pure/near-pure coordination logic already
there (MatchmakingQueue), not bolted onto the PERSISTENCE module that
merely stores whatever number it's handed.

THE STANDARD ELO FORMULA (Arpad Elo's own original system, still the
industry-standard baseline every rating system - chess.com, FIDE,
competitive-game matchmaking generally - either uses directly or
extends from): for a player with `own_rating` facing an opponent rated
`opponent_rating`, the EXPECTED score (a real probability, 0.0-1.0) is
`1 / (1 + 10^((opponent_rating - own_rating) / 400))` - the higher a
player's own rating is relative to their opponent's, the closer this
approaches 1.0 (near-certain expected win); equal ratings always
produce exactly 0.5 for both sides. The new rating is then
`old_rating + K * (actual_score - expected_score)`, where actual_score
is 1 for a win, 0 for a loss (this project has no draws - GameOver
always names exactly one winner, kungfu_chess/client/events/
game_events.py's own GameOver docstring: "the side whose king was NOT
captured" - there is no third outcome to compute for).

K_FACTOR = 32 (this stage's own explicit "choose and document" K-factor
requirement): a common, widely-used default for this exact formula
(e.g. FIDE's own K=40 for new/provisional players, K=20/10 for
established ones; the U.S. Chess Federation and many online rating
systems default to 32 for a broad, non-provisional player pool) - not
tuned or derived from any real data this project has (there is no
historical game corpus to calibrate against), but a reasonable,
standard, easily-justified starting point matching this stage's own
explicit suggestion. A future stage could make this configurable per-
player (e.g. a lower K for established/high-game-count accounts,
mirroring FIDE's own tiered scheme) without this module's own formula
changing at all - `k_factor` is already a parameter, not a hardcoded
literal baked into the calculation, specifically so that door stays
open.

WHY THE DELTA IS COMPUTED ONCE AND APPLIED SYMMETRICALLY, NOT BY
ROUNDING TWO INDEPENDENTLY-COMPUTED NEW RATINGS (this stage's own
explicit "a win/loss pair always moves symmetrically - verify this with
a test" requirement): `expected_loser_score` is always exactly
`1 - expected_winner_score` (the two probabilities are complements of
each other, by the formula's own construction - re-derivable directly:
`1/(1+10^x) + 1/(1+10^-x) = 1` for any x), so the winner's own raw gain
and the loser's own raw loss are ALWAYS identical in exact (unrounded)
arithmetic. Rounding the winner's and loser's own NEW ratings
independently (`round(old + raw_delta)` computed twice, once per side)
could occasionally disagree by one point purely from floating-point/
rounding noise on the two separate computations (e.g. winner's own raw
delta rounds up while the loser's own raw delta, being its exact
negation, happens to round down under Python's own banker's-rounding
`round()`) - `compute_rating_delta` computes and rounds the ONE shared
raw delta ONCE, and `compute_new_ratings` applies `+delta`/`-delta` to
the two starting ratings from that SAME single integer, which
structurally guarantees the two deltas can never independently drift
apart by even one point.

WHY compute_new_ratings RETURNS PLAIN ints, NOT floats: UserRepository's
own `rating` column is declared `INTEGER` (server/persistence/
user_repository.py's own `_CREATE_USERS_TABLE_SQL`) and its own
`update_rating(username, new_rating: int)` signature already expects a
plain int - returning a float here would silently pass SQLite's own
loose type affinity (a REAL value would still "work" in an INTEGER
column) while quietly drifting from the schema's own documented intent;
rounding to the nearest whole rating point here, once, at the one
computation site, is the correct place to make that decision rather
than leaving every caller to remember to round it themselves.
"""

from __future__ import annotations

from typing import Tuple

DEFAULT_K_FACTOR = 32
_ELO_SCALE_FACTOR = 400.0


def expected_score(own_rating: int, opponent_rating: int) -> float:
    """The real, standard ELO expected-score probability for a player
    rated `own_rating` facing an opponent rated `opponent_rating` - see
    module docstring for the full formula/reasoning.

    Args:
        own_rating: The player's own current rating.
        opponent_rating: The opponent's own current rating.

    Returns:
        A float in (0.0, 1.0) - exactly 0.5 when the two ratings are
        equal, approaching 1.0 as `own_rating` grows relative to
        `opponent_rating`, approaching 0.0 as it shrinks.
    """

    return 1.0 / (1.0 + 10.0 ** ((opponent_rating - own_rating) / _ELO_SCALE_FACTOR))


def compute_rating_delta(winner_rating: int, loser_rating: int, k_factor: int = DEFAULT_K_FACTOR) -> int:
    """The single, shared rating-point delta a real win/loss between
    these two ratings produces - see module docstring's "WHY THE DELTA
    IS COMPUTED ONCE..." section for why this is computed exactly once,
    not independently per side.

    Args:
        winner_rating: The winning player's own current rating.
        loser_rating: The losing player's own current rating.
        k_factor: The K-factor to scale the raw expected-score
            difference by - defaults to DEFAULT_K_FACTOR (32).

    Returns:
        A non-negative int (a real win/loss always moves rating in the
        winner's own favor, never against it - `actual_score=1` is
        always >= `expected_score`'s own (0.0, 1.0) range) - the exact
        number of rating points the winner GAINS and the loser LOSES.
    """

    winner_expected_score = expected_score(winner_rating, loser_rating)
    return round(k_factor * (1.0 - winner_expected_score))


def compute_new_ratings(winner_rating: int, loser_rating: int, k_factor: int = DEFAULT_K_FACTOR) -> Tuple[int, int]:
    """The real, new post-game ratings for both players - see module
    docstring for the full formula/reasoning.

    Args:
        winner_rating: The winning player's own current rating.
        loser_rating: The losing player's own current rating.
        k_factor: See compute_rating_delta.

    Returns:
        (new_winner_rating, new_loser_rating) - the winner's own gain
        always exactly equals the loser's own loss (see module
        docstring's own "WHY THE DELTA IS COMPUTED ONCE..." section),
        both plain ints ready to pass directly to
        UserRepository.update_rating.
    """

    delta = compute_rating_delta(winner_rating, loser_rating, k_factor)
    return winner_rating + delta, loser_rating - delta
