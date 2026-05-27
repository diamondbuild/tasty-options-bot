import pytest

from tasty_options_bot.spreads import CreditSpread


def test_credit_spread_calculates_max_profit_and_loss_for_one_wide_spread():
    spread = CreditSpread(short_strike=100, long_strike=99, credit=0.30, quantity=1)

    assert spread.width == 1
    assert spread.max_profit == 30
    assert spread.max_loss == 70
    assert spread.credit_ratio == 0.30


def test_credit_spread_calculates_max_profit_and_loss_for_two_wide_spread():
    spread = CreditSpread(short_strike=100, long_strike=98, credit=0.60, quantity=1)

    assert spread.width == 2
    assert spread.max_profit == 60
    assert spread.max_loss == 140
    assert spread.credit_ratio == 0.30


def test_credit_spread_scales_profit_and_loss_by_quantity():
    spread = CreditSpread(short_strike=100, long_strike=99, credit=0.30, quantity=2)

    assert spread.max_profit == 60
    assert spread.max_loss == 140


def test_credit_spread_rejects_negative_credit():
    with pytest.raises(ValueError, match="credit"):
        CreditSpread(short_strike=100, long_strike=99, credit=-0.01, quantity=1)


def test_credit_spread_rejects_zero_or_negative_width():
    with pytest.raises(ValueError, match="long_strike"):
        CreditSpread(short_strike=100, long_strike=100, credit=0.30, quantity=1)

    with pytest.raises(ValueError, match="long_strike"):
        CreditSpread(short_strike=100, long_strike=101, credit=0.30, quantity=1)


def test_credit_spread_rejects_credit_greater_than_width():
    with pytest.raises(ValueError, match="credit"):
        CreditSpread(short_strike=100, long_strike=99, credit=1.01, quantity=1)


def test_credit_spread_rejects_non_positive_quantity():
    with pytest.raises(ValueError, match="quantity"):
        CreditSpread(short_strike=100, long_strike=99, credit=0.30, quantity=0)
