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
    # v2 rules, learned from the first SMCI round trip:
    # decent gain near expiry -> take it before theta does.
    short_dte_take_profit_dte: int = 5
    short_dte_take_profit_pct: float = 20.0
    # after a +trim-level run, never give back more than this many
    # percentage points from the session peak without locking gains.
    trailing_giveback_pct: float = 25.0


@dataclass(frozen=True)
class YoloExitDecision:
    recommendation: str
    flags: list[str] = field(default_factory=list)
    dte: int = 0
    pnl_at_bid: float = 0.0
    pnl_pct: float = 0.0
    contracts_to_recover_cost: int = 0
    estimated_exit_fees: float = 0.0
    pnl_net_fees: float = 0.0


def evaluate_yolo_position(
    position: YoloPosition,
    *,
    rules: YoloExitRules,
    today: date,
    fees_paid: float = 0.0,
    per_contract_close_fee: float = 0.0,
    peak_pnl_pct: float | None = None,
) -> YoloExitDecision:
    """Evaluate exit rules for a long-option position. Pure function, no I/O.

    Recommendation precedence (highest first):
    SELL_BEFORE_CLOSE > EXIT_THESIS_DEAD > EXIT_OR_ACCEPT_LOSS >
    SELL_HALF > LOCK_GAINS_TRAILING > TRIM > TAKE_PROFIT_SHORT_DTE > HOLD.
    Theta and fee warnings are advisory flags only.

    fees_paid: round-trip fees already incurred on this position.
    per_contract_close_fee: estimated fees per contract to close now.
    peak_pnl_pct: highest pnl_pct observed for this position so far (caller
    tracks it, e.g. from journal history); None disables the trailing rule.
    """
    dte = (position.expiration - today).days
    entry_cost = position.entry_cost
    pnl_at_bid = round(position.value_at_bid - entry_cost, 2)
    pnl_pct = (pnl_at_bid / entry_cost) * 100 if entry_cost else 0.0

    estimated_exit_fees = round(per_contract_close_fee * position.quantity, 2)
    pnl_net_fees = round(pnl_at_bid - fees_paid - estimated_exit_fees, 2)

    contracts_to_recover_cost = 0
    if position.bid > 0:
        contracts_to_recover_cost = min(
            math.ceil(entry_cost / (position.bid * 100)), position.quantity
        )

    flags: list[str] = []
    recommendation = "HOLD"

    # Lowest-precedence first; later rules overwrite the recommendation.
    if (
        0 < dte <= rules.short_dte_take_profit_dte
        and rules.short_dte_take_profit_pct <= pnl_pct < rules.trim_profit_pct
    ):
        recommendation = "TAKE_PROFIT_SHORT_DTE"
        flags.append(
            f"GAIN + SHORT CLOCK: up {pnl_pct:+.0f}% with only {dte} DTE. "
            "Theta will eat this faster than the underlying can outrun it — "
            "take the win (lesson from the first SMCI round trip)."
        )

    if pnl_pct >= rules.trim_profit_pct:
        recommendation = "TRIM"
        flags.append(
            f"PROFIT ALERT: up {pnl_pct:+.0f}% (50%+ threshold). Consider trimming "
            "to lock gains; theta accelerates from here."
        )

    if (
        peak_pnl_pct is not None
        and peak_pnl_pct >= rules.trim_profit_pct
        and (peak_pnl_pct - pnl_pct) >= rules.trailing_giveback_pct
    ):
        recommendation = "LOCK_GAINS_TRAILING"
        flags.append(
            f"TRAILING GIVEBACK: peak was {peak_pnl_pct:+.0f}%, now {pnl_pct:+.0f}% "
            f"(gave back {peak_pnl_pct - pnl_pct:.0f} pts). Do not round-trip a "
            "winner — lock remaining gains."
        )

    if pnl_pct >= rules.sell_half_profit_pct:
        recommendation = "SELL_HALF"
        flags.append(
            f"TAKE-PROFIT ZONE: up {pnl_pct:+.0f}%. Sell half to ride free — "
            f"selling {contracts_to_recover_cost} of {position.quantity} at bid "
            "recovers full cost basis."
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

    if pnl_at_bid > 0 and pnl_net_fees <= 0 and (fees_paid or per_contract_close_fee):
        flags.append(
            f"FEE MIRAGE: gross P/L ${pnl_at_bid:+,.2f} turns into "
            f"${pnl_net_fees:+,.2f} after ${fees_paid + estimated_exit_fees:,.2f} "
            "round-trip fees. This 'win' does not clear the fee bar yet."
        )

    return YoloExitDecision(
        recommendation=recommendation,
        flags=flags,
        dte=dte,
        pnl_at_bid=pnl_at_bid,
        pnl_pct=round(pnl_pct, 2),
        contracts_to_recover_cost=contracts_to_recover_cost,
        estimated_exit_fees=estimated_exit_fees,
        pnl_net_fees=pnl_net_fees,
    )


def _thesis_dead(position: YoloPosition, rules: YoloExitRules) -> bool:
    if rules.thesis_dead_underlying is None or position.underlying_mark is None:
        return False
    if position.option_type.lower() == "call":
        return position.underlying_mark < rules.thesis_dead_underlying
    return position.underlying_mark > rules.thesis_dead_underlying
