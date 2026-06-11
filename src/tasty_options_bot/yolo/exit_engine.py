from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from tasty_options_bot.yolo.models import YoloPosition


@dataclass(frozen=True)
class YoloExitRules:
    """Rule thresholds for managing a long-option YOLO position."""

    trim_profit_pct: float = 50.0
    sell_half_profit_pct: float = 100.0
    stop_loss_pct: float = -50.0
    theta_warning_dte: int = 3
    final_day_dte: int = 1
    thesis_dead_underlying: float | None = None


@dataclass(frozen=True)
class YoloExitDecision:
    recommendation: str
    flags: list[str] = field(default_factory=list)
    dte: int = 0
    pnl_at_bid: float = 0.0
    pnl_pct: float = 0.0
    contracts_to_recover_cost: int = 0


def evaluate_yolo_position(
    position: YoloPosition, *, rules: YoloExitRules, today: date
) -> YoloExitDecision:
    """Evaluate exit rules for a long-option position. Pure function, no I/O.

    Recommendation precedence (highest first):
    SELL_BEFORE_CLOSE > EXIT_THESIS_DEAD > EXIT_OR_ACCEPT_LOSS >
    SELL_HALF > TRIM > HOLD. Theta warnings are advisory flags only.
    """
    dte = (position.expiration - today).days
    entry_cost = position.entry_cost
    pnl_at_bid = round(position.value_at_bid - entry_cost, 2)
    pnl_pct = (pnl_at_bid / entry_cost) * 100 if entry_cost else 0.0

    contracts_to_recover_cost = 0
    if position.bid > 0:
        contracts_to_recover_cost = min(
            math.ceil(entry_cost / (position.bid * 100)), position.quantity
        )

    flags: list[str] = []
    recommendation = "HOLD"

    if pnl_pct >= rules.sell_half_profit_pct:
        recommendation = "SELL_HALF"
        flags.append(
            f"TAKE-PROFIT ZONE: up {pnl_pct:+.0f}%. Sell half to ride free — "
            f"selling {contracts_to_recover_cost} of {position.quantity} at bid "
            "recovers full cost basis."
        )
    elif pnl_pct >= rules.trim_profit_pct:
        recommendation = "TRIM"
        flags.append(
            f"PROFIT ALERT: up {pnl_pct:+.0f}% (50%+ threshold). Consider trimming "
            "to lock gains; theta accelerates from here."
        )

    if pnl_pct <= rules.stop_loss_pct:
        recommendation = "EXIT_OR_ACCEPT_LOSS"
        flags.append(
            f"DOWN {abs(pnl_pct):.0f}% (50%+ stop): decide now — cut and salvage, "
            "or consciously accept full loss. Do not drift."
        )

    if _thesis_dead(position, rules):
        recommendation = "EXIT_THESIS_DEAD"
        flags.append(
            f"THESIS DEAD: {position.underlying_symbol} at "
            f"${position.underlying_mark:.2f} breached "
            f"${rules.thesis_dead_underlying:.2f}. Salvage remaining premium "
            "rather than riding to zero."
        )

    if dte <= rules.final_day_dte:
        recommendation = "SELL_BEFORE_CLOSE"
        flags.append(
            "EXPIRES TOMORROW/TODAY: sell anything with value before the close — "
            "do not let ITM exercise or OTM expiry happen by accident."
        )
    elif dte <= rules.theta_warning_dte:
        flags.append(
            f"ONLY {dte} DTE: theta is brutal now. If the underlying is not "
            "moving your way, exit value decays fast."
        )

    return YoloExitDecision(
        recommendation=recommendation,
        flags=flags,
        dte=dte,
        pnl_at_bid=pnl_at_bid,
        pnl_pct=round(pnl_pct, 2),
        contracts_to_recover_cost=contracts_to_recover_cost,
    )


def _thesis_dead(position: YoloPosition, rules: YoloExitRules) -> bool:
    if rules.thesis_dead_underlying is None or position.underlying_mark is None:
        return False
    if position.option_type.lower() == "call":
        return position.underlying_mark < rules.thesis_dead_underlying
    return position.underlying_mark > rules.thesis_dead_underlying
