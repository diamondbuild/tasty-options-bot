from datetime import date, datetime, timezone

from tasty_options_bot.option_chain import OptionQuote, build_put_credit_spread_candidates


def make_quote(**overrides):
    data = {
        "symbol": "SPY",
        "expiration": date(2026, 7, 2),
        "option_type": "put",
        "option_symbol": "SPY 260702P00600000",
        "strike": 600,
        "delta": -0.20,
        "bid": 1.20,
        "ask": 1.30,
        "quote_time": datetime(2026, 5, 25, 15, 59, tzinfo=timezone.utc),
        "underlying_type": "ETF",
    }
    data.update(overrides)
    return OptionQuote(**data)


def test_option_quote_mid_price_is_bid_ask_average():
    quote = make_quote(bid=1.20, ask=1.30)

    assert quote.mid == 1.25


def test_builds_one_wide_put_credit_spread_candidate_from_chain():
    now = datetime(2026, 5, 25, 16, 0, tzinfo=timezone.utc)
    quotes = [
        make_quote(strike=600, delta=-0.20, bid=1.20, ask=1.30),
        make_quote(
            strike=599,
            delta=-0.12,
            bid=0.90,
            ask=0.95,
            option_symbol="SPY 260702P00599000",
        ),
    ]

    candidates = build_put_credit_spread_candidates(
        quotes=quotes,
        now=now,
        dte_min=30,
        dte_max=45,
        short_delta_min=0.15,
        short_delta_max=0.25,
        spread_widths=[1],
        max_quote_age_seconds=120,
        max_bid_ask_width=0.20,
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.symbol == "SPY"
    assert candidate.dte == 38
    assert candidate.short_strike == 600
    assert candidate.long_strike == 599
    assert candidate.short_option_symbol == "SPY 260702P00600000"
    assert candidate.long_option_symbol == "SPY 260702P00599000"
    assert candidate.credit == 0.32


def test_rejects_expirations_outside_dte_window():
    now = datetime(2026, 5, 25, 16, 0, tzinfo=timezone.utc)
    quotes = [
        make_quote(expiration=date(2026, 6, 10), strike=600, delta=-0.20),
        make_quote(expiration=date(2026, 6, 10), strike=599, delta=-0.12, bid=0.90, ask=0.95),
    ]

    candidates = build_put_credit_spread_candidates(
        quotes=quotes,
        now=now,
        dte_min=30,
        dte_max=45,
        short_delta_min=0.15,
        short_delta_max=0.25,
        spread_widths=[1],
    )

    assert candidates == []


def test_rejects_stale_quotes():
    now = datetime(2026, 5, 25, 16, 0, tzinfo=timezone.utc)
    quotes = [
        make_quote(strike=600, delta=-0.20, quote_time=datetime(2026, 5, 25, 15, 0, tzinfo=timezone.utc)),
        make_quote(strike=599, delta=-0.12, bid=0.90, ask=0.95),
    ]

    candidates = build_put_credit_spread_candidates(
        quotes=quotes,
        now=now,
        dte_min=30,
        dte_max=45,
        short_delta_min=0.15,
        short_delta_max=0.25,
        spread_widths=[1],
        max_quote_age_seconds=120,
    )

    assert candidates == []


def test_rejects_wide_bid_ask_quotes():
    now = datetime(2026, 5, 25, 16, 0, tzinfo=timezone.utc)
    quotes = [
        make_quote(strike=600, delta=-0.20, bid=1.00, ask=1.40),
        make_quote(strike=599, delta=-0.12, bid=0.90, ask=0.95),
    ]

    candidates = build_put_credit_spread_candidates(
        quotes=quotes,
        now=now,
        dte_min=30,
        dte_max=45,
        short_delta_min=0.15,
        short_delta_max=0.25,
        spread_widths=[1],
        max_bid_ask_width=0.20,
    )

    assert candidates == []


def test_rejects_non_put_options():
    now = datetime(2026, 5, 25, 16, 0, tzinfo=timezone.utc)
    quotes = [
        make_quote(option_type="call", strike=600, delta=0.20),
        make_quote(option_type="call", strike=599, delta=0.12, bid=0.90, ask=0.95),
    ]

    candidates = build_put_credit_spread_candidates(
        quotes=quotes,
        now=now,
        dte_min=30,
        dte_max=45,
        short_delta_min=0.15,
        short_delta_max=0.25,
        spread_widths=[1],
    )

    assert candidates == []
