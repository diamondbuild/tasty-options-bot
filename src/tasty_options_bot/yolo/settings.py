from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from tasty_options_bot.yolo.exit_engine import YoloExitRules
from tasty_options_bot.yolo.models import YoloConfig

OCC_SYMBOL_PATTERN = re.compile(
    r"^(?P<root>[A-Z.]{1,6})\s*(?P<date>\d{6})(?P<type>[CP])(?P<strike>\d{8})$"
)


@dataclass(frozen=True)
class ParsedOccSymbol:
    underlying_symbol: str
    expiration: date
    option_type: str
    strike: float


def parse_occ_option_symbol(symbol: str) -> ParsedOccSymbol | None:
    """Parse a tastytrade/OCC option symbol like 'SMCI  260618C00030000'."""
    match = OCC_SYMBOL_PATTERN.match(symbol.strip())
    if match is None:
        return None
    raw_date = match.group("date")
    expiration = date(2000 + int(raw_date[:2]), int(raw_date[2:4]), int(raw_date[4:6]))
    return ParsedOccSymbol(
        underlying_symbol=match.group("root"),
        expiration=expiration,
        option_type="call" if match.group("type") == "C" else "put",
        strike=int(match.group("strike")) / 1000.0,
    )


@dataclass(frozen=True)
class YoloSettings:
    scanner: YoloConfig = field(default_factory=YoloConfig)
    exit_rules: YoloExitRules = field(default_factory=YoloExitRules)
    thesis_dead_levels: dict[str, float] = field(default_factory=dict)
    per_contract_close_fee: float = 0.15


def load_yolo_settings(path: str | Path = "config/yolo.yaml") -> YoloSettings:
    config_path = Path(path)
    raw: dict[str, Any] = {}
    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text())
        if isinstance(loaded, dict):
            raw = loaded

    exit_raw = raw.get("exit_rules", {}) if isinstance(raw.get("exit_rules"), dict) else {}
    thesis_levels_raw = exit_raw.get("thesis_dead_levels", {})
    thesis_dead_levels = (
        {str(k).upper(): float(v) for k, v in thesis_levels_raw.items()}
        if isinstance(thesis_levels_raw, dict)
        else {}
    )

    scanner = YoloConfig(
        budget_per_play=float(raw.get("budget_per_play", 1000.0)),
        dte_min=int(raw.get("dte_min", 5)),
        dte_max=int(raw.get("dte_max", 45)),
        delta_min=float(raw.get("delta_min", 0.25)),
        delta_max=float(raw.get("delta_max", 0.55)),
        max_ask=float(raw.get("max_ask", 5.00)),
        max_bid_ask_width_pct=float(raw.get("max_bid_ask_width_pct", 0.15)),
        max_quote_age_seconds=int(raw.get("max_quote_age_seconds", 120)),
        max_contracts=int(raw.get("max_contracts", 10)),
        universe=[str(s).upper() for s in raw.get("universe", [])],
    )
    exit_rules = YoloExitRules(
        trim_profit_pct=float(exit_raw.get("trim_profit_pct", 50.0)),
        sell_half_profit_pct=float(exit_raw.get("sell_half_profit_pct", 100.0)),
        stop_loss_pct=float(exit_raw.get("stop_loss_pct", -50.0)),
        theta_warning_dte=int(exit_raw.get("theta_warning_dte", 3)),
        final_day_dte=int(exit_raw.get("final_day_dte", 1)),
        thesis_dead_underlying=None,
        short_dte_take_profit_dte=int(exit_raw.get("short_dte_take_profit_dte", 5)),
        short_dte_take_profit_pct=float(
            exit_raw.get("short_dte_take_profit_pct", 20.0)
        ),
        trailing_giveback_pct=float(exit_raw.get("trailing_giveback_pct", 25.0)),
    )
    fees_raw = raw.get("fees", {}) if isinstance(raw.get("fees"), dict) else {}
    per_contract_close_fee = float(fees_raw.get("per_contract_close_fee", 0.15))
    return YoloSettings(
        scanner=scanner,
        exit_rules=exit_rules,
        thesis_dead_levels=thesis_dead_levels,
        per_contract_close_fee=per_contract_close_fee,
    )
