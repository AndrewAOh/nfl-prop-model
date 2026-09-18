import pytest
from nfl_props.pricing.odds import decimal_odds, implied_probability, no_vig_two_way


def test_implied_probability_negative_odds():
    assert implied_probability(-110) == pytest.approx(110 / 210)


def test_decimal_odds():
    assert decimal_odds(-110) == pytest.approx(1 + 100 / 110)
    assert decimal_odds(150) == pytest.approx(2.5)


def test_no_vig_sums_to_one():
    over, under = no_vig_two_way(-110, -110)
    assert over + under == pytest.approx(1.0)
