from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from tasty_options_bot.journal import JournalEvent
from tasty_options_bot.spreads import CreditSpread


@dataclass(frozen=True)
class PositionManagerConfig:
    profit_take_ratio: float = 0.50
    loss_multiple: float = 2.0
    close_dte: int = 21
    expiration_danger_dte: int = 7
    max_loss_breach_ratio: float = 0.85


@dataclass(frozen=True)
class ManagedPosition:
    position_id: str
    symbol: str
    spread: CreditSpread
    expiration: date
    opened_at: date
    opening_credit: float

    def dte(self, today: date) -> int:
        return (self.expiration - today).days

    def pnl_if_closed(self, current_debit: float) -> float:
        return round((self.opening_credit - current_debit) * 100 * self.spread.quantity, 2)


@dataclass(frozen=True)
class ExitDecision:
    position_id: str
    symbol: str
    action: str
    reason: str
    dte: int | None = None
    current_debit: float | None = None
    realized_pnl_if_closed: float | None = None

    def to_journal_event(self) -> JournalEvent:
        return JournalEvent(
            event_type="exit_decision",
            symbol=self.symbol,
            decision=self.action,
            reason=self.reason,
            payload={
                "position_id": self.position_id,
                "dte": self.dte,
                "current_debit": self.current_debit,
                "realized_pnl_if_closed": self.realized_pnl_if_closed,
            },
        )


class PositionManager:
    def __init__(self, config: PositionManagerConfig) -> None:
        self.config = config

    def evaluate(self, position: ManagedPosition, *, current_debit: float, today: date) -> ExitDecision:
        dte = position.dte(today)
        pnl = position.pnl_if_closed(current_debit)
        action = "hold"
        reason = "no_exit_rule_triggered"

        max_loss_breach_debit = round(
            position.opening_credit + ((position.spread.width - position.opening_credit) * self.config.max_loss_breach_ratio),
            4,
        )

        if dte <= self.config.expiration_danger_dte:
            action = "close"
            reason = "expiration_danger_zone"
        elif dte <= self.config.close_dte:
            action = "close"
            reason = "dte_exit_threshold"
        elif current_debit <= position.opening_credit * self.config.profit_take_ratio:
            action = "close"
            reason = "profit_target_hit"
        elif current_debit >= max_loss_breach_debit:
            action = "close"
            reason = "max_loss_breach_near"
        elif current_debit >= position.opening_credit * self.config.loss_multiple:
            action = "close"
            reason = "loss_multiple_hit"

        return ExitDecision(
            position_id=position.position_id,
            symbol=position.symbol,
            action=action,
            reason=reason,
            dte=dte,
            current_debit=current_debit,
            realized_pnl_if_closed=pnl,
        )
