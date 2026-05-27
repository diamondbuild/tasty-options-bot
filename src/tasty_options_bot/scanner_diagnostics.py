from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from statistics import median

from tasty_options_bot.option_chain import OptionQuote, build_put_credit_spread_candidates
from tasty_options_bot.strategy import StrategyConfig


@dataclass(frozen=True)
class CandidateConstructionDiagnostics:
    total_quotes: int
    usable_quotes: int
    candidate_count: int
    rejection_counts: dict[str, int]
    quote_age_seconds: dict[str, float]
    bid_ask_widths: dict[str, float]
    newest_quote_time: datetime | None
    oldest_quote_time: datetime | None


def diagnose_candidate_construction(
    quotes: list[OptionQuote],
    *,
    now: datetime,
    strategy_config: StrategyConfig,
    max_quote_age_seconds: int = 120,
    max_bid_ask_width: float = 0.20,
) -> CandidateConstructionDiagnostics:
    counts: Counter[str] = Counter()
    usable_quotes = 0

    for quote in quotes:
        reason = _base_quote_rejection_reason(
            quote,
            now=now,
            strategy_config=strategy_config,
            max_quote_age_seconds=max_quote_age_seconds,
            max_bid_ask_width=max_bid_ask_width,
        )
        if reason is None:
            usable_quotes += 1
        else:
            counts[reason] += 1

    candidates = build_put_credit_spread_candidates(
        quotes=quotes,
        now=now,
        dte_min=strategy_config.dte_min,
        dte_max=strategy_config.dte_max,
        short_delta_min=strategy_config.short_delta_min,
        short_delta_max=strategy_config.short_delta_max,
        spread_widths=strategy_config.spread_widths,
        max_quote_age_seconds=max_quote_age_seconds,
        max_bid_ask_width=max_bid_ask_width,
    )

    if usable_quotes > 0 and not candidates:
        short_leg_count = sum(
            strategy_config.short_delta_min <= abs(quote.delta) <= strategy_config.short_delta_max
            for quote in quotes
            if _base_quote_rejection_reason(
                quote,
                now=now,
                strategy_config=strategy_config,
                max_quote_age_seconds=max_quote_age_seconds,
                max_bid_ask_width=max_bid_ask_width,
            )
            is None
        )
        if short_leg_count == 0:
            counts["short_delta_out_of_range"] += usable_quotes
            counts["no_short_leg_in_delta_range"] += 1
        else:
            counts["no_matching_long_leg_for_allowed_widths"] += 1

    return CandidateConstructionDiagnostics(
        total_quotes=len(quotes),
        usable_quotes=usable_quotes,
        candidate_count=len(candidates),
        rejection_counts=dict(counts),
        quote_age_seconds=_summary([(now - quote.quote_time).total_seconds() for quote in quotes]),
        bid_ask_widths=_summary([quote.bid_ask_width for quote in quotes]),
        newest_quote_time=max((quote.quote_time for quote in quotes), default=None),
        oldest_quote_time=min((quote.quote_time for quote in quotes), default=None),
    )


def _summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"min": 0.0, "median": 0.0, "max": 0.0}
    return {
        "min": round(min(values), 2),
        "median": round(float(median(values)), 2),
        "max": round(max(values), 2),
    }


def _base_quote_rejection_reason(
    quote: OptionQuote,
    *,
    now: datetime,
    strategy_config: StrategyConfig,
    max_quote_age_seconds: int,
    max_bid_ask_width: float,
) -> str | None:
    if quote.option_type.lower() != "put":
        return "not_put"
    if quote.bid < 0 or quote.ask <= 0 or quote.ask < quote.bid:
        return "invalid_bid_ask"
    if quote.bid_ask_width > max_bid_ask_width:
        return "bid_ask_too_wide"
    if not quote.is_fresh(now, max_quote_age_seconds):
        return "quote_stale"
    dte = (quote.expiration - now.date()).days
    if dte < strategy_config.dte_min:
        return "dte_too_low"
    if dte > strategy_config.dte_max:
        return "dte_too_high"
    return None
