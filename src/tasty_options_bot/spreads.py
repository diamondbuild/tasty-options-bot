from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreditSpread:
    """Defined-risk put credit spread.

    Prices are option premium dollars, not cents. Dollar P/L properties use the
    standard US equity-options multiplier of 100.
    """

    short_strike: float
    long_strike: float
    credit: float
    quantity: int = 1
    multiplier: int = 100

    def __post_init__(self) -> None:
        if self.long_strike >= self.short_strike:
            raise ValueError("long_strike must be below short_strike for a put credit spread")
        if self.credit < 0:
            raise ValueError("credit must be non-negative")
        if self.credit > self.width:
            raise ValueError("credit cannot be greater than spread width")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.multiplier <= 0:
            raise ValueError("multiplier must be positive")

    @property
    def width(self) -> float:
        return round(self.short_strike - self.long_strike, 2)

    @property
    def max_profit(self) -> float:
        return round(self.credit * self.multiplier * self.quantity, 2)

    @property
    def max_loss(self) -> float:
        return round((self.width - self.credit) * self.multiplier * self.quantity, 2)

    @property
    def credit_ratio(self) -> float:
        return round(self.credit / self.width, 4)
