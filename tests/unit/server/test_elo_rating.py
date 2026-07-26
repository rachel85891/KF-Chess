"""Unit tests for server/application/elo_rating.py - a pure, in-memory
ELO computation module, no networking/persistence/GameSession
knowledge at all (mirrors server/application/matchmaking_queue.py's own
"pure, standalone, no I/O" convention - see that module's own docstring
for the precedent this follows). Every rating pair below is a plain
int, exactly what UserRepository.get_rating/update_rating already
store/accept - no test here touches a real database at all.
"""

from __future__ import annotations

from server.application.elo_rating import DEFAULT_K_FACTOR, compute_new_ratings


def test_equal_ratings_produce_the_classic_half_k_factor_swing():
    # The textbook ELO reference value: two equally-rated players (the
    # expected score is exactly 0.5 for both) always swing by exactly
    # half the K-factor, regardless of the ratings' own absolute value.
    winner_new, loser_new = compute_new_ratings(winner_rating=1200, loser_rating=1200)

    assert winner_new == 1200 + DEFAULT_K_FACTOR // 2
    assert loser_new == 1200 - DEFAULT_K_FACTOR // 2


def test_symmetric_win_loss_deltas_for_an_arbitrary_rating_pair():
    # The winner's own gain must always exactly equal the loser's own
    # loss (never independently-rounded, slightly mismatched deltas) -
    # this stage's own explicit "verify this with a test" requirement.
    winner_rating, loser_rating = 1350, 1180

    winner_new, loser_new = compute_new_ratings(winner_rating, loser_rating)

    winner_gain = winner_new - winner_rating
    loser_loss = loser_rating - loser_new
    assert winner_gain == loser_loss
    assert winner_gain > 0  # a real win always gains something (or, at
    # the very least, never loses) - re-verified below for the more
    # extreme cases too.


def test_a_higher_rated_winner_gains_less_than_a_lower_rated_winner_would_for_the_same_win():
    # The single most important, well-known ELO property: winning is
    # worth MORE when you were the underdog, and worth LESS when you
    # were already expected to win.
    favored_winner_new, _ = compute_new_ratings(winner_rating=1600, loser_rating=1200)
    favored_gain = favored_winner_new - 1600

    underdog_winner_new, _ = compute_new_ratings(winner_rating=1200, loser_rating=1600)
    underdog_gain = underdog_winner_new - 1200

    assert underdog_gain > favored_gain


def test_a_huge_underdog_upset_win_gains_nearly_the_full_k_factor():
    # An enormous rating gap (expected score for the eventual winner
    # approaches 0) - the delta should approach, but never exceed, the
    # full K-factor.
    winner_new, _ = compute_new_ratings(winner_rating=1000, loser_rating=2000)

    gain = winner_new - 1000
    assert gain <= DEFAULT_K_FACTOR
    assert gain >= DEFAULT_K_FACTOR - 1  # rounds to essentially the full K


def test_a_heavily_favored_winner_gains_almost_nothing():
    # The mirror image of the above - expected score for the eventual
    # winner approaches 1, so there is almost nothing left to gain.
    winner_new, _ = compute_new_ratings(winner_rating=2000, loser_rating=1000)

    gain = winner_new - 2000
    assert 0 <= gain <= 1


def test_a_custom_k_factor_scales_the_delta_proportionally():
    winner_new_k32, loser_new_k32 = compute_new_ratings(winner_rating=1200, loser_rating=1200, k_factor=32)
    winner_new_k16, loser_new_k16 = compute_new_ratings(winner_rating=1200, loser_rating=1200, k_factor=16)

    assert (winner_new_k32 - 1200) == 2 * (winner_new_k16 - 1200)
    assert (1200 - loser_new_k32) == 2 * (1200 - loser_new_k16)


def test_new_ratings_are_plain_ints_ready_to_persist_via_update_rating():
    # UserRepository.update_rating's own column is `INTEGER` - a float
    # leaking through here would silently truncate or (worse) store a
    # fractional value SQLite would happily accept as REAL-typed
    # affinity data, quietly drifting from the schema's own intent.
    winner_new, loser_new = compute_new_ratings(winner_rating=1234, loser_rating=1187)

    assert isinstance(winner_new, int)
    assert isinstance(loser_new, int)
