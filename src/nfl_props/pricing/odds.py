from __future__ import annotations


def implied_probability(american_odds: int) -> float:
    if american_odds == 0:
        raise ValueError("American odds cannot be zero")
    if american_odds < 0:
        return abs(american_odds) / (abs(american_odds) + 100)
    return 100 / (american_odds + 100)


def decimal_odds(american_odds: int) -> float:
    if american_odds == 0:
        raise ValueError("American odds cannot be zero")
    return 1 + (american_odds / 100 if american_odds > 0 else 100 / abs(american_odds))


def no_vig_two_way(over_price: int, under_price: int) -> tuple[float, float]:
    over = implied_probability(over_price)
    under = implied_probability(under_price)
    total = over + under
    return over / total, under / total


def expected_value(probability: float, american_odds: int) -> float:
    if not 0 <= probability <= 1:
        raise ValueError("Probability must be between 0 and 1")
    dec = decimal_odds(american_odds)
    return probability * (dec - 1) - (1 - probability)
