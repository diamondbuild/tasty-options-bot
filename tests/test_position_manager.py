from datetime import date

from tasty_options_bot.position_manager import (
    ExitDecision,
    ManagedPosition,
    PositionManager,
    PositionManagerConfig,
)
from tasty_options_bot.spreads import CreditSpread


def make_position(**overrides):
    data = {
        "position_id": "pos-1",
        "symbol": "SPY",
        "spread": CreditSpread(short_strike=100, long_strike=99, credit=0.30, quantity=1),
        "expiration": date(2026, 7, 17),
        "opened_at": date(2026, 6, 1),
        "opening_credit": 0.30,
    }
    data.update(overrides)
    return ManagedPosition(**data)


def test_holds_when_no_exit_rule_is_triggered():
    manager = PositionManager(PositionManagerConfig())
    position = make_position()

    decision = manager.evaluate(position, current_debit=0.20, today=date(2026, 6, 10))

    assert decision.action == "hold"
    assert decision.reason == "no_exit_rule_triggered"
    assert decision.position_id == "pos-1"


def test_closes_at_profit_target():
    manager = PositionManager(PositionManagerConfig(profit_take_ratio=0.50))
    position = make_position(opening_credit=0.30)

    decision = manager.evaluate(position, current_debit=0.15, today=date(2026, 6, 10))

    assert decision.action == "close"
    assert decision.reason == "profit_target_hit"
    assert decision.realized_pnl_if_closed == 15.0


def test_closes_at_dte_exit_threshold():
    manager = PositionManager(PositionManagerConfig(close_dte=21))
    position = make_position(expiration=date(2026, 7, 1))

    decision = manager.evaluate(position, current_debit=0.20, today=date(2026, 6, 10))

    assert decision.action == "close"
    assert decision.reason == "dte_exit_threshold"
    assert decision.dte == 21


def test_closes_before_expiration_danger_zone():
    manager = PositionManager(PositionManagerConfig(expiration_danger_dte=7))
    position = make_position(expiration=date(2026, 6, 17))

    decision = manager.evaluate(position, current_debit=0.20, today=date(2026, 6, 10))

    assert decision.action == "close"
    assert decision.reason == "expiration_danger_zone"


def test_closes_when_loss_multiple_hit():
    manager = PositionManager(PositionManagerConfig(loss_multiple=2.0))
    position = make_position(opening_credit=0.30)

    decision = manager.evaluate(position, current_debit=0.60, today=date(2026, 6, 10))

    assert decision.action == "close"
    assert decision.reason == "loss_multiple_hit"
    assert decision.realized_pnl_if_closed == -30.0


def test_closes_when_max_loss_breach_is_near():
    manager = PositionManager(PositionManagerConfig(max_loss_breach_ratio=0.85))
    position = make_position(
        spread=CreditSpread(short_strike=100, long_strike=99, credit=0.20, quantity=1),
        opening_credit=0.20,
    )

    decision = manager.evaluate(position, current_debit=0.88, today=date(2026, 6, 10))

    assert decision.action == "close"
    assert decision.reason == "max_loss_breach_near"


def test_exit_decision_can_be_converted_to_journal_event():
    decision = ExitDecision(
        position_id="pos-1",
        symbol="SPY",
        action="close",
        reason="profit_target_hit",
        dte=30,
        realized_pnl_if_closed=15.0,
    )

    event = decision.to_journal_event()

    assert event.event_type == "exit_decision"
    assert event.symbol == "SPY"
    assert event.decision == "close"
    assert event.reason == "profit_target_hit"
    assert event.payload["position_id"] == "pos-1"
    assert event.payload["dte"] == 30
    assert event.payload["realized_pnl_if_closed"] == 15.0
