from __future__ import annotations

import math
from datetime import datetime

from tasty_options_bot.option_chain import OptionQuote
from tasty_options_bot.yolo.models import YoloCandidate, YoloConfig


def build_yolo_candidates(
    *,
    quotes: list[OptionQuote],
    now: datetime,
    config: YoloConfig,
) -> list[YoloCandidate]:
    """Filter and size long-option YOLO candidates. Pure function, no I/O.

    Sizing: contracts = floor(budget_per_play / (ask * 100)), capped at
    max_contracts. Candidates that cannot afford one contract are rejected.
    Limit price is the current ask (marketable limit, never market orders).
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

        candidates.append(
            YoloCandidate(
                underlying_symbol=quote.symbol,
                option_symbol=quote.option_symbol,
                option_type=quote.option_type.lower(),
                strike=quote.strike,
                expiration=quote.expiration,
                dte=(quote.expiration - now.date()).days,
                delta=quote.delta,
                bid=quote.bid,
                ask=quote.ask,
                contracts=contracts,
                limit_price=limit_price,
                total_cost=round(contracts * limit_price * 100, 2),
                breakeven=breakeven,
            )
        )

    candidates.sort(key=lambda candidate: abs(candidate.delta), reverse=True)
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
