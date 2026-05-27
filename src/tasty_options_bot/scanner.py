from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from tasty_options_bot.journal import Journal, JournalEvent
from tasty_options_bot.option_chain import OptionQuote, build_put_credit_spread_candidates
from tasty_options_bot.risk import RiskManager
from tasty_options_bot.strategy import PutCreditSpreadStrategy, SpreadCandidate


@dataclass(frozen=True)
class ScannerConfig:
    today: date | None = None
    now: datetime | None = None
    open_risk: float = 0.0
    open_positions: int = 0
    account_equity: float | None = None
    realized_pnl_today: float = 0.0
    realized_pnl_week: float = 0.0
    max_quote_age_seconds: int = 120
    max_bid_ask_width: float = 0.20

    @property
    def scan_time(self) -> datetime:
        if self.now is not None:
            return self.now
        return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ScannerDecision:
    action: str
    reason: str
    candidate: SpreadCandidate | None

    def to_journal_event(self) -> JournalEvent:
        payload = {}
        symbol = ""
        if self.candidate is not None:
            symbol = self.candidate.symbol
            payload = {
                "expiration": self.candidate.expiration,
                "dte": self.candidate.dte,
                "short_strike": self.candidate.short_strike,
                "long_strike": self.candidate.long_strike,
                "short_option_symbol": self.candidate.short_option_symbol,
                "long_option_symbol": self.candidate.long_option_symbol,
                "short_delta": self.candidate.short_delta,
                "credit": self.candidate.credit,
                "max_loss": self.candidate.spread.max_loss,
                "credit_ratio": self.candidate.credit_ratio,
            }
        return JournalEvent(
            event_type="scanner_decision",
            symbol=symbol,
            decision=self.action,
            reason=self.reason,
            payload=payload,
        )


class DryRunScanner:
    def __init__(self, *, strategy: PutCreditSpreadStrategy, risk_manager: RiskManager, journal: Journal) -> None:
        self.strategy = strategy
        self.risk_manager = risk_manager
        self.journal = journal

    def scan(self, quotes: list[OptionQuote], *, config: ScannerConfig | None = None) -> list[ScannerDecision]:
        config = config or ScannerConfig()
        candidates = build_put_credit_spread_candidates(
            quotes=quotes,
            now=config.scan_time,
            dte_min=self.strategy.config.dte_min,
            dte_max=self.strategy.config.dte_max,
            short_delta_min=self.strategy.config.short_delta_min,
            short_delta_max=self.strategy.config.short_delta_max,
            spread_widths=self.strategy.config.spread_widths,
            max_quote_age_seconds=config.max_quote_age_seconds,
            max_bid_ask_width=config.max_bid_ask_width,
        )
        decisions: list[ScannerDecision] = []
        for candidate in candidates:
            strategy_decision = self.strategy.evaluate(candidate)
            if not strategy_decision.allowed:
                decision = ScannerDecision("rejected", strategy_decision.reason, candidate)
                self._record(decision)
                decisions.append(decision)
                continue

            risk_decision = self.risk_manager.evaluate_new_position(
                spread=candidate.spread,
                open_risk=config.open_risk,
                open_positions=config.open_positions,
                account_equity=config.account_equity,
                realized_pnl_today=config.realized_pnl_today,
                realized_pnl_week=config.realized_pnl_week,
            )
            if not risk_decision.allowed:
                decision = ScannerDecision("rejected", risk_decision.reason, candidate)
                self._record(decision)
                decisions.append(decision)
                continue

            decision = ScannerDecision("would_trade", "passed_strategy_and_risk", candidate)
            self._record(decision)
            decisions.append(decision)

        return decisions

    def _record(self, decision: ScannerDecision) -> None:
        self.journal.append(decision.to_journal_event())
