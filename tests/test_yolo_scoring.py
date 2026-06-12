from datetime import datetime, timedelta, timezone

from tasty_options_bot.option_chain import OptionQuote
from tasty_options_bot.yolo.models import YoloConfig
from tasty_options_bot.yolo.scanner import build_yolo_candidates, score_candidate

NOW = datetime(2026, 6, 11, 15, 0, tzinfo=timezone.utc)


def make_quote(
    *,
    option_type: str = "call",
    strike: float = 30.0,
    delta: float = 0.40,
    bid: float = 1.30,
    ask: float = 1.40,
    dte: int = 21,
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


def build_one(quote: OptionQuote, *, underlying_mark: float | None = 30.0, **config_overrides):
    config = YoloConfig(universe=["SMCI"], **config_overrides)
    candidates = build_yolo_candidates(
        quotes=[quote], now=NOW, config=config, underlying_mark=underlying_mark
    )
    assert len(candidates) == 1
    return candidates[0]


def test_candidate_carries_score_and_components():
    candidate = build_one(make_quote())
    assert 0.0 <= candidate.score <= 100.0
    assert candidate.spread_tax_pct > 0
    assert candidate.breakeven_move_pct > 0


def test_tighter_spread_scores_higher():
    tight = build_one(make_quote(bid=1.36, ask=1.40))
    wide = build_one(make_quote(bid=1.22, ask=1.40))
    assert tight.score > wide.score
    assert tight.spread_tax_pct < wide.spread_tax_pct


def test_dte_sweet_spot_beats_short_dte():
    """All else equal, ~21 DTE should outrank 6 DTE (theta cliff)."""
    sweet = build_one(make_quote(dte=21))
    short = build_one(make_quote(dte=6))
    assert sweet.score > short.score


def test_smaller_breakeven_move_scores_higher():
    # Underlying approximated via delta-neighborhood: use strike+premium vs spot
    # proxied through breakeven_move_pct: closer strike -> smaller required move.
    near = build_one(make_quote(strike=30.0, bid=1.30, ask=1.40, delta=0.45))
    far = build_one(make_quote(strike=33.0, bid=1.30, ask=1.40, delta=0.30,
                               option_symbol="SMCI  260618C00033000"))
    assert near.breakeven_move_pct < far.breakeven_move_pct
    assert near.score > far.score


def test_candidates_sorted_by_score_descending():
    quotes = [
        make_quote(bid=1.22, ask=1.40, option_symbol="SMCI  260618C00030000"),
        make_quote(bid=1.36, ask=1.40, option_symbol="SMCI  260619C00030000"),
    ]
    config = YoloConfig(universe=["SMCI"])
    candidates = build_yolo_candidates(
        quotes=quotes, now=NOW, config=config, underlying_mark=30.0
    )
    assert len(candidates) == 2
    assert candidates[0].score >= candidates[1].score
    assert candidates[0].option_symbol == "SMCI  260619C00030000"


def test_score_candidate_is_pure_and_bounded():
    candidate = build_one(make_quote())
    score = score_candidate(
        spread_tax_pct=candidate.spread_tax_pct,
        dte=candidate.dte,
        breakeven_move_pct=candidate.breakeven_move_pct,
        delta=candidate.delta,
    )
    assert score == candidate.score
    # extreme inputs stay bounded
    assert 0.0 <= score_candidate(
        spread_tax_pct=99.0, dte=1, breakeven_move_pct=80.0, delta=0.05
    ) <= 100.0
    assert 0.0 <= score_candidate(
        spread_tax_pct=0.5, dte=21, breakeven_move_pct=1.0, delta=0.45
    ) <= 100.0
