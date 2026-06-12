from __future__ import annotations

import math
from datetime import datetime

from tasty_options_bot.option_chain import OptionQuote
from tasty_options_bot.yolo.models import YoloCandidate, YoloConfig

# Score weights (sum to 1.0). Tunable but deterministic — no AI in the loop.
_WEIGHT_SPREAD = 0.35
_WEIGHT_DTE = 0.25
_WEIGHT_BREAKEVEN = 0.25
_WEIGHT_DELTA = 0.15

# Component shaping constants.
_SPREAD_TAX_ZERO_SCORE_PCT = 15.0  # spread tax >= this % of mid scores 0
_DTE_RAMP_LOW = 5
_DTE_SWEET_LOW = 14
_DTE_SWEET_HIGH = 35
_DTE_RAMP_HIGH = 45
_BREAKEVEN_ZERO_SCORE_PCT = 20.0  # required move >= this % scores 0
_DELTA_FLOOR = 0.05
_DELTA_FULL = 0.45


def score_candidate(
    *,
    spread_tax_pct: float,
    dte: int,
    breakeven_move_pct: float,
    delta: float,
) -> float:
    """Composite 0-100 quality score. Pure, deterministic, bounded.

    Components:
    - Spread tax: tighter bid/ask relative to mid is cheaper to enter AND exit.
    - DTE: sweet spot ~14-35 DTE; short DTE sits on the theta cliff, long DTE
      overpays time value for a YOLO horizon.
    - Breakeven move: smaller required underlying move to breakeven is better.
    - Delta: within the allowed band, higher |delta| means less lotto.
    """
    spread_component = _clamp01(1 - spread_tax_pct / _SPREAD_TAX_ZERO_SCORE_PCT)
    dte_component = _dte_component(dte)
    breakeven_component = _clamp01(
        1 - max(breakeven_move_pct, 0.0) / _BREAKEVEN_ZERO_SCORE_PCT
    )
    delta_component = _clamp01(
        (abs(delta) - _DELTA_FLOOR) / (_DELTA_FULL - _DELTA_FLOOR)
    )
    score = 100 * (
        _WEIGHT_SPREAD * spread_component
        + _WEIGHT_DTE * dte_component
        + _WEIGHT_BREAKEVEN * breakeven_component
        + _WEIGHT_DELTA * delta_component
    )
    return round(min(max(score, 0.0), 100.0), 1)


def _dte_component(dte: int) -> float:
    if dte <= _DTE_RAMP_LOW or dte >= _DTE_RAMP_HIGH + 1:
        return 0.0
    if dte < _DTE_SWEET_LOW:
        return (dte - _DTE_RAMP_LOW) / (_DTE_SWEET_LOW - _DTE_RAMP_LOW)
    if dte <= _DTE_SWEET_HIGH:
        return 1.0
    return _clamp01((_DTE_RAMP_HIGH - dte) / (_DTE_RAMP_HIGH - _DTE_SWEET_HIGH))


def _clamp01(value: float) -> float:
    return min(max(value, 0.0), 1.0)


def build_yolo_candidates(
    *,
    quotes: list[OptionQuote],
    now: datetime,
    config: YoloConfig,
    underlying_mark: float | None = None,
) -> list[YoloCandidate]:
    """Filter, size, and score long-option YOLO candidates. Pure function, no I/O.

    Sizing: contracts = floor(budget_per_play / (ask * 100)), capped at
    max_contracts. Candidates that cannot afford one contract are rejected.
    Limit price is the current ask (marketable limit, never market orders).
    Sorted by composite score (descending), |delta| as tie-break.
    """
    candidates: list[YoloCandidate] = []
    for quote in quotes:
        if not _quote_is_usable(quote, now, config):
            continue

        contracts = min(
            math.floor(config.budget_per_play / (quote.ask * 100)),
            config.max_contracts,
        )
        if contracts < 1:
            continue

        limit_price = round(quote.ask, 2)
        if quote.option_type.lower() == "call":
            breakeven = round(quote.strike + limit_price, 2)
        else:
            breakeven = round(quote.strike - limit_price, 2)

        mid = (quote.bid + quote.ask) / 2
        spread_tax_pct = round((quote.ask - quote.bid) / mid * 100, 2)

        breakeven_move_pct = 0.0
        if underlying_mark is not None and underlying_mark > 0:
            if quote.option_type.lower() == "call":
                move = (breakeven - underlying_mark) / underlying_mark
            else:
                move = (underlying_mark - breakeven) / underlying_mark
            breakeven_move_pct = round(move * 100, 2)

        dte = (quote.expiration - now.date()).days
        score = score_candidate(
            spread_tax_pct=spread_tax_pct,
            dte=dte,
            breakeven_move_pct=breakeven_move_pct,
            delta=quote.delta,
        )

        candidates.append(
            YoloCandidate(
                underlying_symbol=quote.symbol,
                option_symbol=quote.option_symbol,
                option_type=quote.option_type.lower(),
                strike=quote.strike,
                expiration=quote.expiration,
                dte=dte,
                delta=quote.delta,
                bid=quote.bid,
                ask=quote.ask,
                contracts=contracts,
                limit_price=limit_price,
                total_cost=round(contracts * limit_price * 100, 2),
                breakeven=breakeven,
                spread_tax_pct=spread_tax_pct,
                breakeven_move_pct=breakeven_move_pct,
                score=score,
            )
        )

    candidates.sort(
        key=lambda candidate: (candidate.score, abs(candidate.delta)), reverse=True
    )
    return candidates


def _quote_is_usable(quote: OptionQuote, now: datetime, config: YoloConfig) -> bool:
    if quote.option_type.lower() not in {"call", "put"}:
        return False
    if quote.bid < 0 or quote.ask <= 0 or quote.ask < quote.bid:
        return False
    if quote.ask > config.max_ask:
        return False
    if not (config.delta_min <= abs(quote.delta) <= config.delta_max):
        return False
    if not quote.is_fresh(now, config.max_quote_age_seconds):
        return False

    mid = (quote.bid + quote.ask) / 2
    if mid <= 0 or (quote.ask - quote.bid) / mid > config.max_bid_ask_width_pct:
        return False

    dte = (quote.expiration - now.date()).days
    return config.dte_min <= dte <= config.dte_max
