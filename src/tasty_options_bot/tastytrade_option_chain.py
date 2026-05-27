from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class TastytradeOptionContract:
    underlying_symbol: str
    option_symbol: str
    streamer_symbol: str
    expiration: date
    dte: int
    strike: float
    option_type: str


def parse_nested_option_chain(
    items: list[dict[str, Any]],
    *,
    option_type: str | None = None,
    dte_min: int | None = None,
    dte_max: int | None = None,
) -> list[TastytradeOptionContract]:
    contracts: list[TastytradeOptionContract] = []
    requested_type = option_type.lower() if option_type else None

    for chain in items:
        underlying = str(chain.get("underlying-symbol", ""))
        for expiration_data in chain.get("expirations", []):
            expiration = date.fromisoformat(str(expiration_data["expiration-date"]))
            dte = int(expiration_data.get("days-to-expiration", 0))
            if dte_min is not None and dte < dte_min:
                continue
            if dte_max is not None and dte > dte_max:
                continue
            for strike_data in expiration_data.get("strikes", []):
                strike = float(strike_data["strike-price"])
                for contract_type in ["call", "put"]:
                    if requested_type and contract_type != requested_type:
                        continue
                    option_symbol = strike_data.get(contract_type)
                    streamer_symbol = strike_data.get(f"{contract_type}-streamer-symbol")
                    if not option_symbol or not streamer_symbol:
                        continue
                    contracts.append(
                        TastytradeOptionContract(
                            underlying_symbol=underlying,
                            option_symbol=str(option_symbol),
                            streamer_symbol=str(streamer_symbol),
                            expiration=expiration,
                            dte=dte,
                            strike=strike,
                            option_type=contract_type,
                        )
                    )
    return contracts
