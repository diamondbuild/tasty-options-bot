from __future__ import annotations

from datetime import datetime
from typing import Any

from tasty_options_bot.option_chain import OptionQuote
from tasty_options_bot.tastytrade_option_chain import TastytradeOptionContract


def parse_equity_option_market_data(
    items: list[dict[str, Any]], contracts: list[TastytradeOptionContract]
) -> list[OptionQuote]:
    contracts_by_symbol = {contract.option_symbol: contract for contract in contracts}
    quotes: list[OptionQuote] = []

    for item in items:
        symbol = str(item.get("symbol", ""))
        contract = contracts_by_symbol.get(symbol)
        if contract is None:
            continue
        try:
            bid = float(item["bid"])
            ask = float(item["ask"])
            delta = float(item["delta"])
            quote_time = _parse_timestamp(str(item["updated-at"]))
        except (KeyError, TypeError, ValueError):
            continue

        quotes.append(
            OptionQuote(
                symbol=contract.underlying_symbol,
                expiration=contract.expiration,
                option_type=contract.option_type,
                strike=contract.strike,
                delta=delta,
                bid=bid,
                ask=ask,
                quote_time=quote_time,
                option_symbol=contract.option_symbol,
            )
        )

    return quotes


def _parse_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)
