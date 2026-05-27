from tasty_options_bot.risk import AccountRiskLimits, RiskManager
from tasty_options_bot.spreads import CreditSpread


def test_allows_spread_within_position_and_account_limits():
    limits = AccountRiskLimits(max_position_loss=100, max_open_risk=400, max_open_positions=3)
    manager = RiskManager(limits=limits)
    spread = CreditSpread(short_strike=100, long_strike=99, credit=0.30, quantity=1)

    decision = manager.evaluate_new_position(spread=spread, open_risk=0, open_positions=0)

    assert decision.allowed
    assert decision.reason == "allowed"


def test_rejects_spread_above_max_position_loss():
    limits = AccountRiskLimits(max_position_loss=100, max_open_risk=400, max_open_positions=3)
    manager = RiskManager(limits=limits)
    spread = CreditSpread(short_strike=100, long_strike=98, credit=0.60, quantity=1)

    decision = manager.evaluate_new_position(spread=spread, open_risk=0, open_positions=0)

    assert not decision.allowed
    assert "max_position_loss" in decision.reason


def test_rejects_trade_when_total_open_risk_would_exceed_limit():
    limits = AccountRiskLimits(max_position_loss=100, max_open_risk=400, max_open_positions=3)
    manager = RiskManager(limits=limits)
    spread = CreditSpread(short_strike=100, long_strike=99, credit=0.30, quantity=1)

    decision = manager.evaluate_new_position(spread=spread, open_risk=350, open_positions=1)

    assert not decision.allowed
    assert "max_open_risk" in decision.reason


def test_rejects_trade_when_max_positions_already_reached():
    limits = AccountRiskLimits(max_position_loss=100, max_open_risk=400, max_open_positions=3)
    manager = RiskManager(limits=limits)
    spread = CreditSpread(short_strike=100, long_strike=99, credit=0.30, quantity=1)

    decision = manager.evaluate_new_position(spread=spread, open_risk=100, open_positions=3)

    assert not decision.allowed
    assert "max_open_positions" in decision.reason


def test_rejects_trade_when_kill_switch_active():
    limits = AccountRiskLimits(
        max_position_loss=100,
        max_open_risk=400,
        max_open_positions=3,
        kill_switch_active=True,
    )
    manager = RiskManager(limits=limits)
    spread = CreditSpread(short_strike=100, long_strike=99, credit=0.30, quantity=1)

    decision = manager.evaluate_new_position(spread=spread, open_risk=0, open_positions=0)

    assert not decision.allowed
    assert "kill_switch" in decision.reason


def test_rejects_trade_when_account_equity_is_at_or_below_shutdown_equity():
    limits = AccountRiskLimits(
        max_position_loss=100,
        max_open_risk=400,
        max_open_positions=3,
        shutdown_equity=2400,
    )
    manager = RiskManager(limits=limits)
    spread = CreditSpread(short_strike=100, long_strike=99, credit=0.30, quantity=1)

    decision = manager.evaluate_new_position(
        spread=spread,
        open_risk=0,
        open_positions=0,
        account_equity=2400,
    )

    assert not decision.allowed
    assert "shutdown_equity" in decision.reason


def test_rejects_trade_when_daily_realized_loss_limit_is_reached():
    limits = AccountRiskLimits(
        max_position_loss=100,
        max_open_risk=400,
        max_open_positions=3,
        max_daily_loss=150,
    )
    manager = RiskManager(limits=limits)
    spread = CreditSpread(short_strike=100, long_strike=99, credit=0.30, quantity=1)

    decision = manager.evaluate_new_position(
        spread=spread,
        open_risk=0,
        open_positions=0,
        realized_pnl_today=-150,
    )

    assert not decision.allowed
    assert decision.reason == "max_daily_loss_reached"


def test_rejects_trade_when_weekly_realized_loss_limit_is_reached():
    limits = AccountRiskLimits(
        max_position_loss=100,
        max_open_risk=400,
        max_open_positions=3,
        max_weekly_loss=300,
    )
    manager = RiskManager(limits=limits)
    spread = CreditSpread(short_strike=100, long_strike=99, credit=0.30, quantity=1)

    decision = manager.evaluate_new_position(
        spread=spread,
        open_risk=0,
        open_positions=0,
        realized_pnl_week=-301,
    )

    assert not decision.allowed
    assert decision.reason == "max_weekly_loss_reached"
