from datetime import date, datetime, timedelta, timezone

from tasty_options_bot.option_chain import OptionQuote
from tasty_options_bot.yolo.models import YoloConfig
from tasty_options_bot.yolo.scanner import build_yolo_candidates

NOW = datetime(2026, 6, 11, 15, 0, tzinfo=timezone.utc)


def make_quote(
    *,
    option_type: str = "call",
    strike: float = 30.0,
    delta: float = 0.40,
    bid: float = 1.30,
    ask: float = 1.40,
    dte: int = 10,
    age_seconds: int = 5,
    symbol: str = "SMCI",
    option_symbol: str = "SMCI  260618C00030000",
) -> OptionQuote:
    return OptionQuote(
        symbol=symbol,
        expiration=NOW.date() + timedelta(days=dte),
        option_type=option_type,
        strike=strike,
        delta=delta,
        bid=bid,
        ask=ask,
        quote_time=NOW - timedelta(seconds=age_seconds),
        option_symbol=option_symbol,
    )


def default_config(**overrides) -> YoloConfig:
    base = {
        "budget_per_play": 1000.0,
        "dte_min": 5,
        "dte_max": 45,
        "delta_min": 0.25,
        "delta_max": 0.55,
        "max_ask": 5.00,
        "max_bid_ask_width_pct": 0.15,
        "max_quote_age_seconds": 120,
    }
    base.update(overrides)
    return YoloConfig(**base)


def test_accepts_call_in_band_and_sizes_by_budget():
    candidates = build_yolo_candidates(
        quotes=[make_quote()], now=NOW, config=default_config()
    )
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.strategy_label == "Long Call (YOLO)"
    assert candidate.option_symbol == "SMCI  260618C00030000"
    # floor(1000 / (1.40 * 100)) = 7
    assert candidate.contracts == 7
    assert candidate.total_cost == 980.0
    assert candidate.breakeven == 31.40


def test_put_candidate_breakeven_below_strike():
    quote = make_quote(
        option_type="put",
        delta=-0.40,
        option_symbol="SMCI  260618P00030000",
    )
    candidates = build_yolo_candidates(
        quotes=[quote], now=NOW, config=default_config()
    )
    assert len(candidates) == 1
    assert candidates[0].strategy_label == "Long Put (YOLO)"
    assert candidates[0].breakeven == 28.60


def test_rejects_outside_dte_band():
    too_short = make_quote(dte=2)
    too_long = make_quote(dte=60)
    assert build_yolo_candidates(quotes=[too_short, too_long], now=NOW, config=default_config()) == []


def test_rejects_outside_delta_band_absolute():
    lotto = make_quote(delta=0.05)
    deep_itm = make_quote(delta=0.80)
    assert build_yolo_candidates(quotes=[lotto, deep_itm], now=NOW, config=default_config()) == []


def test_rejects_when_ask_exceeds_cap_or_budget_too_small_for_one():
    expensive = make_quote(bid=6.00, ask=6.20)
    assert build_yolo_candidates(quotes=[expensive], now=NOW, config=default_config()) == []
    tiny_budget = default_config(budget_per_play=100.0)
    assert build_yolo_candidates(quotes=[make_quote()], now=NOW, config=tiny_budget) == []


def test_rejects_wide_or_stale_or_crossed_quotes():
    wide = make_quote(bid=1.00, ask=1.40)  # width 0.40 > 15% of 1.20 mid
    stale = make_quote(age_seconds=600)
    crossed = make_quote(bid=1.50, ask=1.40)
    zero_ask = make_quote(bid=0.0, ask=0.0)
    quotes = [wide, stale, crossed, zero_ask]
    assert build_yolo_candidates(quotes=quotes, now=NOW, config=default_config()) == []


def test_candidates_sorted_by_delta_descending():
    a = make_quote(delta=0.30, option_symbol="SMCI  260618C00032000", strike=32.0)
    b = make_quote(delta=0.50, option_symbol="SMCI  260618C00029000", strike=29.0)
    candidates = build_yolo_candidates(quotes=[a, b], now=NOW, config=default_config())
    assert [c.option_symbol for c in candidates] == [
        "SMCI  260618C00029000",
        "SMCI  260618C00032000",
    ]


def test_contracts_capped_by_max_contracts():
    config = default_config(budget_per_play=10000.0, max_contracts=9)
    candidates = build_yolo_candidates(quotes=[make_quote()], now=NOW, config=config)
    assert candidates[0].contracts == 9


def test_expiration_preserved_as_date():
    candidates = build_yolo_candidates(quotes=[make_quote(dte=7)], now=NOW, config=default_config())
    assert candidates[0].expiration == date(2026, 6, 18)
    assert candidates[0].dte == 7
