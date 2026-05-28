from __future__ import annotations

from dataclasses import dataclass

from tasty_options_bot.spreads import CreditSpread


@dataclass(frozen=True)
class AccountRiskLimits:
    max_position_loss: float = 100.0
    max_open_risk: float = 400.0
    max_open_positions: int = 2
    max_daily_loss: float = 150.0
    max_weekly_loss: float = 300.0
    shutdown_equity: float = 2400.0
    kill_switch_active: bool = False


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class RiskManager:
    limits: AccountRiskLimits

    def evaluate_new_position(
        self,
        *,
        spread: CreditSpread,
        open_risk: float,
        open_positions: int,
        account_equity: float | None = None,
        realized_pnl_today: float = 0.0,
        realized_pnl_week: float = 0.0,
    ) -> RiskDecision:
        if self.limits.kill_switch_active:
            return RiskDecision(False, "kill_switch_active")

        if account_equity is not None and account_equity <= self.limits.shutdown_equity:
            return RiskDecision(False, "shutdown_equity_reached")

        if realized_pnl_today <= -self.limits.max_daily_loss:
            return RiskDecision(False, "max_daily_loss_reached")

        if realized_pnl_week <= -self.limits.max_weekly_loss:
            return RiskDecision(False, "max_weekly_loss_reached")

        if open_positions >= self.limits.max_open_positions:
            return RiskDecision(False, "max_open_positions_exceeded")

        if spread.max_loss > self.limits.max_position_loss:
            return RiskDecision(False, "max_position_loss_exceeded")

        if open_risk + spread.max_loss > self.limits.max_open_risk:
            return RiskDecision(False, "max_open_risk_exceeded")

        return RiskDecision(True, "allowed")
