from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from tasty_options_bot.strategy import SpreadCandidate


@dataclass(frozen=True)
class OptionQuote:
    symbol: str
    expiration: date
    option_type: str
    strike: float
    delta: float
    bid: float
    ask: float
    quote_time: datetime
    option_symbol: str = ""
    underlying_type: str = "ETF"

    @property
    def mid(self) -> float:
        return round((self.bid + self.ask) / 2, 2)

    @property
    def bid_ask_width(self) -> float:
        return round(self.ask - self.bid, 2)

    def is_fresh(self, now: datetime, max_quote_age_seconds: int) -> bool:
        return (now - self.quote_time).total_seconds() <= max_quote_age_seconds


@dataclass(frozen=True)
class OptionChainFilters:
    dte_min: int = 30
    dte_max: int = 45
    short_delta_min: float = 0.15
    short_delta_max: float = 0.25
    spread_widths: list[int] | None = None
    max_quote_age_seconds: int = 120
    max_bid_ask_width: float = 0.20

    @property
    def allowed_spread_widths(self) -> list[int]:
        return self.spread_widths or [1, 2]


def build_put_credit_spread_candidates(
    *,
    quotes: list[OptionQuote],
    now: datetime,
    dte_min: int = 30,
    dte_max: int = 45,
    short_delta_min: float = 0.15,
    short_delta_max: float = 0.25,
    spread_widths: list[int] | None = None,
    max_quote_age_seconds: int = 120,
    max_bid_ask_width: float = 0.20,
) -> list[SpreadCandidate]:
    filters = OptionChainFilters(
        dte_min=dte_min,
        dte_max=dte_max,
        short_delta_min=short_delta_min,
        short_delta_max=short_delta_max,
        spread_widths=spread_widths,
        max_quote_age_seconds=max_quote_age_seconds,
        max_bid_ask_width=max_bid_ask_width,
    )
    valid_quotes = [_quote for _quote in quotes if _quote_is_usable(_quote, now, filters)]
    by_key = {(_quote.symbol, _quote.expiration, _quote.strike): _quote for _quote in valid_quotes}
    candidates: list[SpreadCandidate] = []

    for short_quote in valid_quotes:
        if not (filters.short_delta_min <= abs(short_quote.delta) <= filters.short_delta_max):
            continue

        dte = (short_quote.expiration - now.date()).days
        for width in filters.allowed_spread_widths:
            long_strike = short_quote.strike - width
            long_quote = by_key.get((short_quote.symbol, short_quote.expiration, long_strike))
            if long_quote is None:
                continue
            credit = round(short_quote.mid - long_quote.mid, 2)
            if credit <= 0:
                continue
            candidates.append(
                SpreadCandidate(
                    symbol=short_quote.symbol,
                    expiration=short_quote.expiration.isoformat(),
                    dte=dte,
                    short_strike=short_quote.strike,
                    long_strike=long_quote.strike,
                    short_delta=short_quote.delta,
                    credit=credit,
                    option_type=short_quote.option_type,
                    short_option_symbol=short_quote.option_symbol,
                    long_option_symbol=long_quote.option_symbol,
                    underlying_type=short_quote.underlying_type,
                )
            )

    return candidates


def _quote_is_usable(quote: OptionQuote, now: datetime, filters: OptionChainFilters) -> bool:
    if quote.option_type.lower() != "put":
        return False
    if quote.bid < 0 or quote.ask <= 0 or quote.ask < quote.bid:
        return False
    if quote.bid_ask_width > filters.max_bid_ask_width:
        return False
    if not quote.is_fresh(now, filters.max_quote_age_seconds):
        return False

    dte = (quote.expiration - now.date()).days
    return filters.dte_min <= dte <= filters.dte_max
