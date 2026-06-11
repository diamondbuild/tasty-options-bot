from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class YoloConfig:
    """Filters and sizing for the YOLO long-option scanner."""

    budget_per_play: float = 1000.0
    dte_min: int = 5
    dte_max: int = 45
    delta_min: float = 0.25
    delta_max: float = 0.55
    max_ask: float = 5.00
    max_bid_ask_width_pct: float = 0.15
    max_quote_age_seconds: int = 120
    max_contracts: int = 10
    universe: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class YoloCandidate:
    """A sized, preview-only long-option candidate."""

    underlying_symbol: str
    option_symbol: str
    option_type: str
    strike: float
    expiration: date
    dte: int
    delta: float
    bid: float
    ask: float
    contracts: int
    limit_price: float
    total_cost: float
    breakeven: float

    @property
    def strategy_label(self) -> str:
        side = "Call" if self.option_type.lower() == "call" else "Put"
        return f"Long {side} (YOLO)"


@dataclass(frozen=True)
class YoloPosition:
    """An open long-option position with live quote context."""

    option_symbol: str
    underlying_symbol: str
    option_type: str
    strike: float
    expiration: date
    quantity: int
    entry_price: float
    bid: float
    ask: float
    mark: float
    underlying_mark: float | None = None

    @property
    def entry_cost(self) -> float:
        return round(self.entry_price * 100 * self.quantity, 2)

    @property
    def value_at_bid(self) -> float:
        return round(self.bid * 100 * self.quantity, 2)

    @property
    def value_at_mark(self) -> float:
        return round(self.mark * 100 * self.quantity, 2)
