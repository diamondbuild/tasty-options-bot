from datetime import date, datetime, timedelta, timezone

from tasty_options_bot.option_chain import OptionQuote
from tasty_options_bot.scanner_diagnostics import diagnose_candidate_construction
from tasty_options_bot.strategy import StrategyConfig


def make_quote(**overrides):
    now = datetime(2026, 6, 1, 14, 30, tzinfo=timezone.utc)
    data = {
        "symbol": "SPY",
        "expiration": date(2026, 7, 16),
        "option_type": "put",
        "strike": 100.0,
        "delta": -0.20,
        "bid": 0.30,
        "ask": 0.34,
        "quote_time": now,
    }
    data.update(overrides)
    return OptionQuote(**data)


def test_diagnostics_counts_stale_quotes():
    now = datetime(2026, 6, 1, 14, 35, tzinfo=timezone.utc)
    quotes = [make_quote(quote_time=now - timedelta(minutes=5))]

    diagnostics = diagnose_candidate_construction(quotes, now=now, strategy_config=StrategyConfig())

    assert diagnostics.total_quotes == 1
    assert diagnostics.rejection_counts["quote_stale"] == 1
    assert diagnostics.candidate_count == 0


def test_diagnostics_respects_configurable_quote_age_and_bid_ask_width():
    now = datetime(2026, 6, 1, 14, 35, tzinfo=timezone.utc)
    quotes = [
        make_quote(strike=100, delta=-0.20, bid=0.30, ask=0.70, quote_time=now - timedelta(minutes=5)),
        make_quote(strike=99, delta=-0.10, bid=0.02, ask=0.32, quote_time=now - timedelta(minutes=5)),
    ]

    diagnostics = diagnose_candidate_construction(
        quotes,
        now=now,
        strategy_config=StrategyConfig(spread_widths=[1]),
        max_quote_age_seconds=600,
        max_bid_ask_width=0.50,
    )

    assert diagnostics.usable_quotes == 2
    assert diagnostics.candidate_count == 1
    assert diagnostics.rejection_counts == {}


def test_diagnostics_reports_quote_age_and_width_summaries():
    now = datetime(2026, 6, 1, 14, 35, tzinfo=timezone.utc)
    quotes = [
        make_quote(bid=0.10, ask=0.40, quote_time=now - timedelta(seconds=30)),
        make_quote(bid=0.10, ask=1.60, quote_time=now - timedelta(seconds=120)),
        make_quote(bid=0.10, ask=2.60, quote_time=now - timedelta(seconds=300)),
    ]

    diagnostics = diagnose_candidate_construction(quotes, now=now, strategy_config=StrategyConfig())

    assert diagnostics.quote_age_seconds == {"min": 30.0, "median": 120.0, "max": 300.0}
    assert diagnostics.bid_ask_widths == {"min": 0.3, "median": 1.5, "max": 2.5}
    assert diagnostics.newest_quote_time == now - timedelta(seconds=30)
    assert diagnostics.oldest_quote_time == now - timedelta(seconds=300)


def test_diagnostics_counts_delta_and_missing_long_leg():
    now = datetime(2026, 6, 1, 14, 30, tzinfo=timezone.utc)
    quotes = [
        make_quote(strike=100, delta=-0.30),
        make_quote(strike=99, delta=-0.10),
    ]

    diagnostics = diagnose_candidate_construction(quotes, now=now, strategy_config=StrategyConfig(spread_widths=[1]))

    assert diagnostics.total_quotes == 2
    assert diagnostics.rejection_counts["short_delta_out_of_range"] == 2
    assert diagnostics.candidate_count == 0


def test_diagnostics_reports_buildable_candidate_count():
    now = datetime(2026, 6, 1, 14, 30, tzinfo=timezone.utc)
    quotes = [
        make_quote(strike=100, delta=-0.20, bid=0.30, ask=0.34),
        make_quote(strike=99, delta=-0.10, bid=0.02, ask=0.04),
    ]

    diagnostics = diagnose_candidate_construction(quotes, now=now, strategy_config=StrategyConfig(spread_widths=[1]))

    assert diagnostics.candidate_count == 1
    assert diagnostics.rejection_counts == {}
