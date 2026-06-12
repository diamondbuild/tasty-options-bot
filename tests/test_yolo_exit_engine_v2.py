"""Tests for the v2 exit-engine rules learned from the first SMCI round trip:

- fee-aware P/L (the 9-lot paid $11.28 in fees; thin wins can be fee mirages)
- gain + short DTE = take it (we exited +23% at 7 DTE rather than ride theta)
- trailing lock after a big run (never round-trip a +50% gain back to flat)
"""

from datetime import date

from tasty_options_bot.yolo.exit_engine import (
    YoloExitRules,
    evaluate_yolo_position,
)
from tasty_options_bot.yolo.models import YoloPosition

TODAY = date(2026, 6, 11)


def make_position(
    *,
    quantity: int = 9,
    entry_price: float = 1.43,
    bid: float = 1.30,
    ask: float = 1.38,
    mark: float = 1.34,
    expiration: date = date(2026, 6, 18),
    underlying_mark: float | None = 29.34,
) -> YoloPosition:
    return YoloPosition(
        option_symbol="SMCI  260618C00030000",
        underlying_symbol="SMCI",
        option_type="call",
        strike=30.0,
        expiration=expiration,
        quantity=quantity,
        entry_price=entry_price,
        bid=bid,
        ask=ask,
        mark=mark,
        underlying_mark=underlying_mark,
    )


def default_rules(**overrides) -> YoloExitRules:
    base = {
        "trim_profit_pct": 50.0,
        "sell_half_profit_pct": 100.0,
        "stop_loss_pct": -50.0,
        "theta_warning_dte": 3,
        "final_day_dte": 1,
        "thesis_dead_underlying": 27.0,
    }
    base.update(overrides)
    return YoloExitRules(**base)


# --- fee-aware P/L ---------------------------------------------------------


def test_fee_adjusted_pnl_reported():
    decision = evaluate_yolo_position(
        make_position(),
        rules=default_rules(),
        today=TODAY,
        fees_paid=10.11,
        per_contract_close_fee=0.13,
    )
    # raw pnl at bid: -117.0; fees already paid 10.11; closing 9 more ~1.17
    assert decision.pnl_at_bid == -117.0
    assert decision.estimated_exit_fees == 1.17
    assert decision.pnl_net_fees == -128.28


def test_fee_mirage_flagged_when_gross_win_is_net_loss():
    # entry 1.43, bid 1.44 -> gross +$1.00 on 1 contract, but fees eat it
    decision = evaluate_yolo_position(
        make_position(quantity=1, bid=1.44, mark=1.45, ask=1.46),
        rules=default_rules(),
        today=TODAY,
        fees_paid=1.25,
        per_contract_close_fee=0.13,
    )
    assert decision.pnl_at_bid > 0
    assert decision.pnl_net_fees < 0
    assert any("fee" in flag.lower() for flag in decision.flags)


def test_fees_default_to_zero_and_keep_old_behavior():
    decision = evaluate_yolo_position(
        make_position(), rules=default_rules(), today=TODAY
    )
    assert decision.estimated_exit_fees == 0.0
    assert decision.pnl_net_fees == decision.pnl_at_bid


# --- gain + short DTE = take it -------------------------------------------


def test_take_profit_short_dte_when_decent_gain_near_expiry():
    # +23% with 5 DTE: not at trim threshold, but theta will eat it
    rules = default_rules(short_dte_take_profit_dte=7, short_dte_take_profit_pct=20.0)
    decision = evaluate_yolo_position(
        make_position(bid=1.76, mark=1.80, ask=1.84, expiration=date(2026, 6, 16)),
        rules=rules,
        today=TODAY,
    )
    assert decision.recommendation == "TAKE_PROFIT_SHORT_DTE"
    assert any("theta" in flag.lower() for flag in decision.flags)


def test_no_short_dte_take_profit_when_gain_below_threshold():
    rules = default_rules(short_dte_take_profit_dte=7, short_dte_take_profit_pct=20.0)
    decision = evaluate_yolo_position(
        make_position(bid=1.50, mark=1.55, ask=1.60, expiration=date(2026, 6, 16)),
        rules=rules,
        today=TODAY,
    )
    assert decision.recommendation == "HOLD"


def test_no_short_dte_take_profit_when_plenty_of_time():
    rules = default_rules(short_dte_take_profit_dte=7, short_dte_take_profit_pct=20.0)
    decision = evaluate_yolo_position(
        make_position(bid=1.76, mark=1.80, ask=1.84, expiration=date(2026, 8, 21)),
        rules=rules,
        today=TODAY,
    )
    assert decision.recommendation == "HOLD"


def test_stronger_rules_beat_short_dte_take_profit():
    # stop loss outranks the take-profit nudge
    rules = default_rules(short_dte_take_profit_dte=7, short_dte_take_profit_pct=20.0)
    decision = evaluate_yolo_position(
        make_position(bid=0.60, mark=0.65, ask=0.70, expiration=date(2026, 6, 16)),
        rules=rules,
        today=TODAY,
    )
    assert decision.recommendation == "EXIT_OR_ACCEPT_LOSS"


# --- trailing lock after a run --------------------------------------------


def test_trailing_lock_triggers_after_giveback_from_peak():
    # peaked at +80%, now +35%: gave back more than 25 points -> lock gains
    rules = default_rules(trailing_giveback_pct=25.0)
    decision = evaluate_yolo_position(
        make_position(bid=1.93, mark=1.97, ask=2.01),  # ~ +35%
        rules=rules,
        today=TODAY,
        peak_pnl_pct=80.0,
    )
    assert decision.recommendation == "LOCK_GAINS_TRAILING"
    assert any("peak" in flag.lower() for flag in decision.flags)


def test_no_trailing_lock_when_still_near_peak():
    rules = default_rules(trailing_giveback_pct=25.0)
    decision = evaluate_yolo_position(
        make_position(bid=2.36, mark=2.40, ask=2.44),  # ~ +65%
        rules=rules,
        today=TODAY,
        peak_pnl_pct=80.0,
    )
    assert decision.recommendation != "LOCK_GAINS_TRAILING"


def test_no_trailing_lock_when_peak_never_reached_trim_threshold():
    # peak +30% never armed the trail; current +5% is just a HOLD
    rules = default_rules(trailing_giveback_pct=25.0)
    decision = evaluate_yolo_position(
        make_position(bid=1.50, mark=1.55, ask=1.60),
        rules=rules,
        today=TODAY,
        peak_pnl_pct=30.0,
    )
    assert decision.recommendation == "HOLD"


def test_trailing_lock_not_triggered_without_peak_history():
    rules = default_rules(trailing_giveback_pct=25.0)
    decision = evaluate_yolo_position(
        make_position(bid=1.93, mark=1.97, ask=2.01),
        rules=rules,
        today=TODAY,
    )
    assert decision.recommendation != "LOCK_GAINS_TRAILING"
