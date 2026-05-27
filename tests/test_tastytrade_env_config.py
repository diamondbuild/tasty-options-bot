import os

from tasty_options_bot.config import TastytradeConfig, load_tastytrade_config_from_env


def test_tastytrade_config_loads_from_environment(monkeypatch):
    monkeypatch.setenv("TASTYTRADE_USERNAME", "user")
    monkeypatch.setenv("TASTYTRADE_PASSWORD", "pass")
    monkeypatch.setenv("TASTYTRADE_ACCOUNT_NUMBER", "5WT00000")
    monkeypatch.setenv("TASTYTRADE_IS_PRODUCTION", "false")
    monkeypatch.setenv("BOT_LIVE_TRADING", "false")
    monkeypatch.setenv("BOT_REQUIRE_MANUAL_APPROVAL", "true")

    config = load_tastytrade_config_from_env()

    assert config.username == "user"
    assert config.password_value == "pass"
    assert config.account_number == "5WT00000"
    assert config.is_production is False
    assert config.live_trading is False
    assert config.require_manual_approval is True


def test_tastytrade_config_defaults_to_safe_flags_when_env_missing(monkeypatch):
    for key in list(os.environ):
        if key.startswith("TASTYTRADE_") or key.startswith("BOT_"):
            monkeypatch.delenv(key, raising=False)

    config = load_tastytrade_config_from_env(env_path=None)

    assert config.is_production is False
    assert config.live_trading is False
    assert config.require_manual_approval is True


def test_tastytrade_config_rejects_truthy_live_trading_without_manual_approval(monkeypatch):
    monkeypatch.setenv("BOT_LIVE_TRADING", "true")
    monkeypatch.setenv("BOT_REQUIRE_MANUAL_APPROVAL", "false")

    config = load_tastytrade_config_from_env()

    assert config.live_trading is True
    assert config.require_manual_approval is False


def test_tastytrade_config_type_has_no_secret_repr():
    config = TastytradeConfig(username="user", password="secret", account_number="5WT00000")

    assert "secret" not in repr(config)
