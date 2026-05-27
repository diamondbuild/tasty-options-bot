from __future__ import annotations

from dataclasses import dataclass, field

from tasty_options_bot.spreads import CreditSpread


@dataclass(frozen=True)
class StrategyConfig:
    enabled: list[str] = field(default_factory=lambda: ["put_credit_spread"])
    universe: list[str] = field(
        default_factory=lambda: ["SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "TLT", "GLD"]
    )
    dte_min: int = 30
    dte_max: int = 45
    short_delta_min: float = 0.15
    short_delta_max: float = 0.25
    spread_widths: list[int] = field(default_factory=lambda: [1, 2])
    min_credit_ratio: float = 0.25
    profit_take_ratio: float = 0.50
    loss_multiple: float = 2.0
    close_dte: int = 21
    etfs_only: bool = True


@dataclass(frozen=True)
class StrategyDecision:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class SpreadCandidate:
    symbol: str
    expiration: str
    dte: int
    short_strike: float
    long_strike: float
    short_delta: float
    credit: float
    option_type: str = "put"
    short_option_symbol: str = ""
    long_option_symbol: str = ""
    underlying_type: str = "ETF"
    quantity: int = 1

    @property
    def spread(self) -> CreditSpread:
        return CreditSpread(
            short_strike=self.short_strike,
            long_strike=self.long_strike,
            credit=self.credit,
            quantity=self.quantity,
        )

    @property
    def credit_ratio(self) -> float:
        return self.spread.credit_ratio

    @property
    def abs_short_delta(self) -> float:
        return abs(self.short_delta)

    @property
    def strategy_label(self) -> str:
        normalized_type = self.option_type.lower()
        if normalized_type == "put":
            return "Put Credit Spread"
        if normalized_type == "call":
            return "Call Credit Spread"
        return f"{self.option_type.title()} Credit Spread"


@dataclass(frozen=True)
class PutCreditSpreadStrategy:
    config: StrategyConfig

    def evaluate(self, candidate: SpreadCandidate) -> StrategyDecision:
        if self.config.etfs_only and candidate.underlying_type.upper() != "ETF":
            return StrategyDecision(False, "underlying_type_not_etf")

        if candidate.symbol not in self.config.universe:
            return StrategyDecision(False, "symbol_not_in_universe")

        if candidate.dte < self.config.dte_min:
            return StrategyDecision(False, "dte_min_not_met")

        if candidate.dte > self.config.dte_max:
            return StrategyDecision(False, "dte_max_exceeded")

        if candidate.abs_short_delta < self.config.short_delta_min:
            return StrategyDecision(False, "short_delta_min_not_met")

        if candidate.abs_short_delta > self.config.short_delta_max:
            return StrategyDecision(False, "short_delta_max_exceeded")

        if candidate.spread.width not in self.config.spread_widths:
            return StrategyDecision(False, "spread_width_not_allowed")

        if candidate.credit_ratio < self.config.min_credit_ratio:
            return StrategyDecision(False, "min_credit_ratio_not_met")

        return StrategyDecision(True, "allowed")
