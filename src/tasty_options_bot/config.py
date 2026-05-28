from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, SecretStr


class AccountConfig(BaseModel):
    starting_equity: float = 3000.0
    max_position_loss: float = 100.0
    max_open_risk: float = 400.0
    max_open_positions: int = 2
    max_daily_loss: float = 150.0
    max_weekly_loss: float = 300.0
    shutdown_equity: float = 2400.0


class StrategyConfig(BaseModel):
    enabled: list[str] = Field(default_factory=lambda: ["put_credit_spread"])
    universe: list[str] = Field(
        default_factory=lambda: ["SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "TLT", "GLD"]
    )
    dte_min: int = 30
    dte_max: int = 45
    short_delta_min: float = 0.15
    short_delta_max: float = 0.25
    spread_widths: list[int] = Field(default_factory=lambda: [1, 2])
    min_credit_ratio: float = 0.25
    profit_take_ratio: float = 0.50
    loss_multiple: float = 2.0
    close_dte: int = 21


class ExecutionConfig(BaseModel):
    live_trading: bool = False
    require_manual_approval: bool = True
    order_type: str = "limit"
    allow_market_orders: bool = False
    max_contracts_per_trade: int = 1
    kill_switch_active: bool = False


class BotConfig(BaseModel):
    account: AccountConfig = Field(default_factory=AccountConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)


class TastytradeConfig(BaseModel):
    username: str = ""
    password: SecretStr = SecretStr("")
    account_number: str = ""
    is_production: bool = False
    live_trading: bool = False
    require_manual_approval: bool = True

    @property
    def password_value(self) -> str:
        return self.password.get_secret_value()


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text())
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected mapping in {path}")
    return loaded


def load_config(config_dir: str | Path = "config") -> BotConfig:
    config_path = Path(config_dir)
    return BotConfig(
        account=AccountConfig(**_read_yaml(config_path / "account.yaml")),
        strategy=StrategyConfig(**_read_yaml(config_path / "strategy.yaml")),
        execution=ExecutionConfig(**_read_yaml(config_path / "execution.yaml")),
    )


def load_dotenv(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_tastytrade_config_from_env(env_path: str | Path | None = ".env") -> TastytradeConfig:
    if env_path is not None:
        load_dotenv(env_path)
    return TastytradeConfig(
        username=os.getenv("TASTYTRADE_USERNAME", ""),
        password=SecretStr(os.getenv("TASTYTRADE_PASSWORD", "")),
        account_number=os.getenv("TASTYTRADE_ACCOUNT_NUMBER", ""),
        is_production=_env_bool("TASTYTRADE_IS_PRODUCTION", default=False),
        live_trading=_env_bool("BOT_LIVE_TRADING", default=False),
        require_manual_approval=_env_bool("BOT_REQUIRE_MANUAL_APPROVAL", default=True),
    )


def _env_bool(key: str, *, default: bool) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}
