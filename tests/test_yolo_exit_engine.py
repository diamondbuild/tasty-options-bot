from datetime import date

from tasty_options_bot.yolo.exit_engine import YoloExitRules, evaluate_yolo_position
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


def test_hold_when_no_rules_triggered():
    decision = evaluate_yolo_position(make_position(), rules=default_rules(), today=TODAY)
    assert decision.recommendation == "HOLD"
    assert decision.flags == []
    assert decision.dte == 7
    # P/L at bid: 1.30*900 - 1.43*900 = -117
    assert decision.pnl_at_bid == -117.0
    assert round(decision.pnl_pct, 1) == -9.1


def test_trim_at_50_percent_profit():
    decision = evaluate_yolo_position(
        make_position(bid=2.20, mark=2.25, ask=2.30), rules=default_rules(), today=TODAY
    )
    assert decision.recommendation == "TRIM"
    assert any("50%" in flag for flag in decision.flags)


def test_sell_half_at_100_percent_profit_outranks_trim():
    decision = evaluate_yolo_position(
        make_position(bid=2.90, mark=2.95, ask=3.00), rules=default_rules(), today=TODAY
    )
    assert decision.recommendation == "SELL_HALF"
    assert any("half" in flag.lower() for flag in decision.flags)


def test_stop_loss_forces_decision():
    decision = evaluate_yolo_position(
        make_position(bid=0.60, mark=0.65, ask=0.70), rules=default_rules(), today=TODAY
    )
    assert decision.recommendation == "EXIT_OR_ACCEPT_LOSS"
    assert any("50%" in flag for flag in decision.flags)


def test_thesis_dead_underlying_triggers_exit():
    decision = evaluate_yolo_position(
        make_position(underlying_mark=26.50), rules=default_rules(), today=TODAY
    )
    assert decision.recommendation == "EXIT_THESIS_DEAD"


def test_no_thesis_check_when_underlying_unknown_or_unconfigured():
    decision = evaluate_yolo_position(
        make_position(underlying_mark=None), rules=default_rules(), today=TODAY
    )
    assert decision.recommendation == "HOLD"
    rules = default_rules(thesis_dead_underlying=None)
    decision = evaluate_yolo_position(
        make_position(underlying_mark=26.50), rules=rules, today=TODAY
    )
    assert decision.recommendation == "HOLD"


def test_put_thesis_dead_is_underlying_above_level():
    position = YoloPosition(
        option_symbol="SMCI  260618P00030000",
        underlying_symbol="SMCI",
        option_type="put",
        strike=30.0,
        expiration=date(2026, 6, 18),
        quantity=2,
        entry_price=1.00,
        bid=0.95,
        ask=1.05,
        mark=1.00,
        underlying_mark=33.0,
    )
    decision = evaluate_yolo_position(
        position, rules=default_rules(thesis_dead_underlying=32.0), today=TODAY
    )
    assert decision.recommendation == "EXIT_THESIS_DEAD"


def test_theta_warning_near_expiry():
    decision = evaluate_yolo_position(
        make_position(expiration=date(2026, 6, 13)), rules=default_rules(), today=TODAY
    )
    assert decision.recommendation == "HOLD"
    assert any("theta" in flag.lower() for flag in decision.flags)


def test_final_day_sell_anything_with_value():
    decision = evaluate_yolo_position(
        make_position(expiration=date(2026, 6, 12)), rules=default_rules(), today=TODAY
    )
    assert decision.recommendation == "SELL_BEFORE_CLOSE"


def test_sell_half_contracts_recovers_cost_basis():
    # entry cost 1287; at bid 2.90 selling 5 contracts recovers 1450 >= 1287
    decision = evaluate_yolo_position(
        make_position(bid=2.90, mark=2.95, ask=3.00), rules=default_rules(), today=TODAY
    )
    assert decision.contracts_to_recover_cost == 5
