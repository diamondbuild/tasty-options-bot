from tasty_options_bot.config import BotConfig, ExecutionConfig, load_config


def test_safe_execution_defaults_disable_live_trading():
    config = ExecutionConfig()

    assert config.live_trading is False
    assert config.require_manual_approval is True
    assert config.allow_market_orders is False
    assert config.max_contracts_per_trade == 1
    assert config.kill_switch_active is False


def test_safe_account_defaults_match_small_account_risk_limits():
    config = BotConfig()

    assert config.account.starting_equity == 3000
    assert config.account.max_position_loss == 100
    assert config.account.max_open_risk == 400
    assert config.account.max_open_positions == 2
    assert config.account.shutdown_equity == 2400


def test_strategy_defaults_are_put_credit_spreads_only():
    config = BotConfig()

    assert config.strategy.enabled == ["put_credit_spread"]
    assert config.strategy.dte_min == 30
    assert config.strategy.dte_max == 45
    assert config.strategy.short_delta_min == 0.15
    assert config.strategy.short_delta_max == 0.25
    assert config.strategy.spread_widths == [1, 2]
    assert config.strategy.min_credit_ratio == 0.25
    assert config.strategy.profit_take_ratio == 0.50
    assert config.strategy.loss_multiple == 2.0
    assert config.strategy.close_dte == 21


def test_load_config_uses_safe_defaults_when_no_files_are_provided(tmp_path):
    config = load_config(config_dir=tmp_path)

    assert config.execution.live_trading is False
    assert config.execution.require_manual_approval is True
    assert config.account.max_position_loss == 100


def test_load_config_overrides_known_values_from_yaml(tmp_path):
    (tmp_path / "account.yaml").write_text("max_position_loss: 75\nmax_open_positions: 1\n")
    (tmp_path / "execution.yaml").write_text("require_manual_approval: false\nkill_switch_active: true\n")

    config = load_config(config_dir=tmp_path)

    assert config.account.max_position_loss == 75
    assert config.account.max_open_positions == 1
    assert config.execution.require_manual_approval is False
    assert config.execution.live_trading is False
    assert config.execution.kill_switch_active is True
