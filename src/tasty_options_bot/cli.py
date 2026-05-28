"""CLI entrypoint for tasty-options-bot."""

import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import typer
import yaml
from rich.console import Console
from rich.table import Table

from tasty_options_bot import __version__
from tasty_options_bot.broker.tastytrade_client import TastytradeClient, TastytradeClientConfig
from tasty_options_bot.config import load_config, load_tastytrade_config_from_env
from tasty_options_bot.dashboard import serve_dashboard
from tasty_options_bot.journal import Journal, JournalEvent, realized_pnl_totals
from tasty_options_bot.order_ticket import (
    ClosingCreditSpreadTicket,
    OpeningCreditSpreadTicket,
    build_closing_credit_spread_ticket,
    build_opening_credit_spread_ticket,
    build_tastytrade_closing_order_payload,
    build_tastytrade_opening_order_payload,
)
from tasty_options_bot.option_chain import OptionQuote
from tasty_options_bot.position_manager import ManagedPosition, PositionManager, PositionManagerConfig
from tasty_options_bot.reports import build_operator_report, write_markdown_report
from tasty_options_bot.risk import AccountRiskLimits, RiskManager
from tasty_options_bot.scanner import DryRunScanner, ScannerConfig
from tasty_options_bot.scanner_diagnostics import diagnose_candidate_construction
from tasty_options_bot.spreads import CreditSpread
from tasty_options_bot.strategy import PutCreditSpreadStrategy, StrategyConfig
from tasty_options_bot.tastytrade_market_data import parse_equity_option_market_data
from tasty_options_bot.tastytrade_option_chain import parse_nested_option_chain

app = typer.Typer(help="Defined-risk tastytrade options bot.", no_args_is_help=True)
console = Console()


def build_tastytrade_client() -> TastytradeClient:
    env_config = load_tastytrade_config_from_env()
    client_config = TastytradeClientConfig(
        username=env_config.username,
        password=env_config.password_value,
        account_number=env_config.account_number,
        is_production=env_config.is_production,
        live_trading=env_config.live_trading,
        require_manual_approval=env_config.require_manual_approval,
    )
    return TastytradeClient(client_config)


def authenticate_client(client: TastytradeClient) -> None:
    login_result = client.login()
    if login_result != "device_challenge_required":
        return

    challenge = client.start_device_challenge()
    phone = challenge.get("phone", "your registered device")
    console.print(f"Device challenge required. OTP sent to {phone}.")
    otp = typer.prompt("Enter tastytrade OTP code")
    client.complete_login_with_otp(otp)


@app.command()
def version() -> None:
    """Print package version."""
    console.print(__version__)


@app.command()
def risk_status(
    journal_path: Path = typer.Option(Path("data/journal.jsonl"), help="Audit journal JSONL path."),
) -> None:
    """Print configured risk limits and execution safety flags."""
    config = load_config()
    journal = Journal(journal_path)
    console.print("Risk status")
    console.print(f"Starting equity: ${config.account.starting_equity:,.2f}")
    console.print(f"Max position loss: ${config.account.max_position_loss:,.2f}")
    console.print(f"Max open risk: ${config.account.max_open_risk:,.2f}")
    console.print(f"Max open positions: {config.account.max_open_positions}")
    console.print(f"Shutdown equity: ${config.account.shutdown_equity:,.2f}")
    console.print(f"Live trading: {config.execution.live_trading}")
    console.print(f"Manual approval required: {config.execution.require_manual_approval}")
    console.print(f"Market orders allowed: {config.execution.allow_market_orders}")
    console.print(f"Kill switch active: {_effective_kill_switch_active(config, journal)}")


@app.command("operator-runbook")
def operator_runbook() -> None:
    """Print the safe daily operating workflow for the bot."""
    console.print("Safe daily operator runbook")
    console.print("1. Pre-flight readiness")
    console.print("   .venv/bin/python -m tasty_options_bot.cli readiness-check --broker-check")
    console.print("2. Reconcile submitted orders")
    console.print("   .venv/bin/python -m tasty_options_bot.cli reconcile-submitted-orders")
    console.print("3. Manage open live positions")
    console.print("   .venv/bin/python -m tasty_options_bot.cli manage-live-positions --symbol SPY")
    console.print("4. Run dry-run scheduler")
    console.print("   .venv/bin/python -m tasty_options_bot.cli scheduler --symbol SPY --cycles 1")
    console.print("5. Manual live submit")
    console.print("   Only after reviewing readiness, positions, reconciliation, and preview output.")
    console.print(
        "   .venv/bin/python -m tasty_options_bot.cli live-dry-run SPY --best-only --ticket-preview "
        "--submit-open --i-understand-live-order --confirm-symbol SPY"
    )
    console.print("No commands in this runbook submit orders except the explicitly manual live-submit example.")


@app.command("readiness-check")
def readiness_check(
    broker_check: bool = typer.Option(False, help="Fetch broker positions read-only and include them in readiness."),
    journal_path: Path = typer.Option(Path("data/journal.jsonl"), help="Audit journal JSONL path."),
) -> None:
    """Print a read-only pre-flight checklist for scheduler and live-submit safety."""
    config = load_config()
    journal = Journal(journal_path)
    kill_switch_active = _effective_kill_switch_active(config, journal)
    unresolved_open_orders = _has_unresolved_open_order(journal)
    closed_ids = _closed_manual_position_ids(journal)
    open_journal_positions = []
    for event in journal.read_recent(limit=1000):
        if event.event_type not in {"manual_live_trade_entered", "live_open_order_filled"}:
            continue
        position_id = _position_id_from_open_event(event)
        if position_id in closed_ids or position_id in open_journal_positions:
            continue
        open_journal_positions.append(position_id)

    last_reconciliation = "none"
    for event in journal.read_recent(limit=1000):
        if event.event_type in {
            "live_open_order_reconciled",
            "live_open_order_filled",
            "live_close_order_reconciled",
            "live_close_order_filled",
            "exit_decision",
        }:
            last_reconciliation = f"{event.event_type}:{event.decision}"
            break

    broker_symbols: set[str] | None = None
    if broker_check:
        client = build_tastytrade_client()
        authenticate_client(client)
        broker_symbols = _position_symbols(client.get_positions())

    broker_has_positions = bool(broker_symbols) if broker_symbols is not None else False
    blockers = []
    if not config.execution.live_trading:
        blockers.append("live_trading_disabled")
    if kill_switch_active:
        blockers.append("kill_switch_active")
    if unresolved_open_orders:
        blockers.append("unresolved_submitted_opening_order")
    if open_journal_positions:
        blockers.append("journal_open_position")
    if broker_has_positions:
        blockers.append("broker_open_position")
    if broker_symbols is None:
        blockers.append("broker_positions_not_checked")

    console.print("Readiness check")
    console.print(f"Live trading: {config.execution.live_trading}")
    console.print(f"Manual approval required: {config.execution.require_manual_approval}")
    console.print(f"Market orders allowed: {config.execution.allow_market_orders}")
    console.print(f"Kill switch active: {kill_switch_active}")
    console.print(f"Unresolved submitted opening orders: {unresolved_open_orders}")
    console.print(f"Journal open positions: {bool(open_journal_positions)}")
    if open_journal_positions:
        console.print(f"Journal position ids: {', '.join(open_journal_positions)}")
    console.print(f"Last reconciliation status: {last_reconciliation}")
    if broker_symbols is None:
        console.print("Broker positions: not checked")
    else:
        console.print("Broker positions checked: True")
        console.print(f"Broker open positions: {broker_has_positions}")
        if broker_symbols:
            console.print(f"Broker symbols: {', '.join(sorted(broker_symbols))}")
    console.print(f"Live submit readiness: {'READY' if not blockers else 'BLOCKED'}")
    if blockers:
        console.print(f"Blockers: {', '.join(blockers)}")
    console.print("No orders were placed; readiness-check is read-only.")


def _latest_kill_switch_journal_state(journal: Journal) -> bool | None:
    for event in journal.read_recent(limit=1000):
        if event.event_type != "kill_switch_changed":
            continue
        state = event.payload.get("kill_switch_active")
        if isinstance(state, bool):
            return state
    return None


def _effective_kill_switch_active(config, journal: Journal) -> bool:
    journal_state = _latest_kill_switch_journal_state(journal)
    if journal_state is not None:
        return journal_state
    return bool(config.execution.kill_switch_active)


@app.command("kill-switch")
def kill_switch(
    action: str = typer.Argument(..., help="status, enable, or disable."),
    journal_path: Path = typer.Option(Path("data/journal.jsonl"), help="Audit journal JSONL path."),
) -> None:
    """Inspect or persistently toggle the bot kill switch in the audit journal."""
    normalized_action = action.lower().strip()
    if normalized_action not in {"status", "enable", "disable"}:
        raise typer.BadParameter("action must be one of: status, enable, disable")

    config = load_config()
    journal = Journal(journal_path)
    if normalized_action == "status":
        console.print(f"Kill switch active: {_effective_kill_switch_active(config, journal)}")
        return

    active = normalized_action == "enable"
    journal.append(
        JournalEvent(
            event_type="kill_switch_changed",
            symbol="",
            decision="enabled" if active else "disabled",
            reason="operator_requested",
            payload={"kill_switch_active": active},
        )
    )
    console.print(f"Kill switch {'enabled' if active else 'disabled'}")
    console.print(f"Journal path: {journal_path}")


@app.command()
def login_check() -> None:
    """Authenticate to tastytrade and print safe connection status."""
    client = build_tastytrade_client()
    authenticate_client(client)
    console.print("Login OK")
    console.print(f"Base URL: {client.config.base_url}")
    console.print(f"Account configured: {bool(client.config.account_number)}")
    console.print(f"Live trading: {client.config.live_trading}")


@app.command()
def account() -> None:
    """Fetch tastytrade account details read-only."""
    client = build_tastytrade_client()
    authenticate_client(client)
    data = client.get_account()
    table = Table(title="Tastytrade Account")
    table.add_column("Field")
    table.add_column("Value")
    for key in sorted(data):
        table.add_row(str(key), str(data[key]))
    console.print(table)


@app.command()
def positions() -> None:
    """Fetch tastytrade positions read-only."""
    client = build_tastytrade_client()
    authenticate_client(client)
    items = client.get_positions()
    table = Table(title="Tastytrade Positions")
    table.add_column("Symbol")
    table.add_column("Quantity")
    table.add_column("Instrument Type")
    if not items:
        console.print("No positions returned.")
        return
    for item in items:
        table.add_row(
            str(item.get("symbol", "")),
            str(item.get("quantity", "")),
            str(item.get("instrument-type", item.get("instrument_type", ""))),
        )
    console.print(table)


@app.command()
def balance() -> None:
    """Fetch tastytrade balance details read-only."""
    client = build_tastytrade_client()
    authenticate_client(client)
    data = client.get_balance()
    table = Table(title="Tastytrade Balance")
    table.add_column("Field")
    table.add_column("Value")
    for key in sorted(data):
        table.add_row(str(key), str(data[key]))
    console.print(table)


def _apply_live_dry_run_preset(
    *,
    preset: str | None,
    spread_width: list[int] | None,
    min_credit_ratio: float | None,
    short_delta_min: float | None,
    short_delta_max: float | None,
    max_position_loss: float | None,
    max_open_risk: float | None,
    max_open_positions: int | None,
) -> dict[str, object]:
    values = {
        "spread_width": spread_width,
        "min_credit_ratio": min_credit_ratio,
        "short_delta_min": short_delta_min,
        "short_delta_max": short_delta_max,
        "max_position_loss": max_position_loss,
        "max_open_risk": max_open_risk,
        "max_open_positions": max_open_positions,
    }
    if preset is None:
        return values
    if preset != "five-wide-research":
        raise typer.BadParameter("supported presets: five-wide-research")

    preset_values = {
        "spread_width": [5],
        "min_credit_ratio": 0.18,
        "short_delta_min": 0.20,
        "short_delta_max": 0.30,
        "max_position_loss": 425.0,
        "max_open_risk": 850.0,
        "max_open_positions": 2,
    }
    for key, value in preset_values.items():
        if values[key] is None:
            values[key] = value
    return values


def _load_watchlist_symbols(universe_path: Path) -> list[str]:
    loaded = yaml.safe_load(universe_path.read_text()) if universe_path.exists() else None
    if loaded is None:
        config = load_config()
        raw_symbols = config.strategy.universe
    elif isinstance(loaded, dict):
        raw_symbols = loaded.get("symbols", [])
    elif isinstance(loaded, list):
        raw_symbols = loaded
    else:
        raise typer.BadParameter(f"Expected symbols list in {universe_path}")

    symbols: list[str] = []
    seen: set[str] = set()
    for raw_symbol in raw_symbols:
        symbol = str(raw_symbol).upper().strip()
        if not symbol or symbol in seen:
            continue
        symbols.append(symbol)
        seen.add(symbol)
    return symbols


@app.command("scan-watchlist")
def scan_watchlist(
    symbols: list[str] | None = typer.Option(None, "--symbol", "-s", help="Symbol to scan. Repeat to override config/universe.yaml."),
    universe_path: Path = typer.Option(Path("config/universe.yaml"), help="YAML watchlist path with a symbols list."),
    max_symbols: int = typer.Option(20, help="Maximum watchlist symbols to scan in one read-only run."),
    dte_min: int = 30,
    dte_max: int = 45,
    max_contracts: int = 100,
    max_quote_age_seconds: int = 120,
    max_bid_ask_width: float = 0.20,
    spread_width: list[int] | None = typer.Option(None, "--spread-width", help="Allowed spread width. Repeat for multiple widths."),
    min_credit_ratio: float | None = typer.Option(None, help="Research-only minimum credit / spread width override."),
    short_delta_min: float | None = typer.Option(None, help="Research-only short delta minimum override."),
    short_delta_max: float | None = typer.Option(None, help="Research-only short delta maximum override."),
    max_position_loss: float | None = typer.Option(None, help="Research-only max position loss override."),
    max_open_risk: float | None = typer.Option(None, help="Research-only max open risk override."),
    max_open_positions: int | None = typer.Option(None, help="Research-only max open positions override."),
    preset: str | None = typer.Option(None, help="Research preset. Currently supported: five-wide-research."),
    best_only: bool = typer.Option(True, help="Show only the highest-ranked decision per symbol."),
    ticket_preview: bool = typer.Option(True, help="Show non-submitting ticket previews for matching symbols."),
    journal_path: Path = typer.Option(Path("data/journal.jsonl"), help="Audit journal JSONL path."),
    max_results: int = typer.Option(10, help="Maximum decisions to display per symbol."),
) -> None:
    """Run read-only live dry-run scans across a configured watchlist."""
    if max_symbols <= 0:
        raise typer.BadParameter("--max-symbols must be positive")

    selected_symbols = [symbol.upper().strip() for symbol in symbols or [] if symbol.strip()]
    if not selected_symbols:
        selected_symbols = _load_watchlist_symbols(universe_path)
    selected_symbols = selected_symbols[:max_symbols]
    if not selected_symbols:
        console.print("No watchlist symbols configured.")
        return

    console.print(f"Watchlist scan: {len(selected_symbols)} symbols")
    for selected_symbol in selected_symbols:
        console.rule(f"{selected_symbol} dry-run scan")
        live_dry_run(
            symbol=selected_symbol,
            dte_min=dte_min,
            dte_max=dte_max,
            max_contracts=max_contracts,
            max_quote_age_seconds=max_quote_age_seconds,
            max_bid_ask_width=max_bid_ask_width,
            spread_width=spread_width,
            min_credit_ratio=min_credit_ratio,
            short_delta_min=short_delta_min,
            short_delta_max=short_delta_max,
            max_position_loss=max_position_loss,
            max_open_risk=max_open_risk,
            max_open_positions=max_open_positions,
            preset=preset,
            best_only=best_only,
            ticket_preview=ticket_preview,
            submit_open=False,
            i_understand_live_order=False,
            confirm_symbol=None,
            max_entry_leg_bid_ask_width=None,
            journal_path=journal_path,
            max_results=max_results,
        )
    console.print("Dry-run watchlist scan only: no orders were placed.")


def _rank_decisions(decisions):
    def key(decision):
        candidate = decision.candidate
        if candidate is None:
            return (1, 0.0, 0.0, 0.0)
        return (
            0 if decision.action == "would_trade" else 1,
            -candidate.credit_ratio,
            candidate.spread.max_loss,
            abs(abs(candidate.short_delta) - 0.24),
        )

    return sorted(decisions, key=key)


def _format_decision_row(decision, *, starting_equity: float) -> list[str]:
    candidate = decision.candidate
    if candidate is None:
        return [decision.action, decision.reason, "", "", "", "", "", "", "", "", "", "", "", "", ""]
    account_risk = ""
    if starting_equity > 0:
        account_risk = f"{candidate.spread.max_loss / starting_equity:.1%}"
    return [
        decision.action,
        decision.reason,
        candidate.strategy_label,
        candidate.expiration,
        str(candidate.dte),
        f"{candidate.short_strike:.2f}",
        f"{candidate.long_strike:.2f}",
        candidate.short_option_symbol,
        candidate.long_option_symbol,
        f"{candidate.spread.width:.2f}",
        f"{candidate.short_delta:.2f}",
        f"{candidate.credit:.2f}",
        f"{candidate.credit_ratio:.1%}",
        f"{candidate.spread.max_loss:.2f}",
        account_risk,
    ]


def _build_strategy(
    config,
    *,
    min_credit_ratio: float | None = None,
    spread_widths: list[int] | None = None,
    short_delta_min: float | None = None,
    short_delta_max: float | None = None,
) -> PutCreditSpreadStrategy:
    return PutCreditSpreadStrategy(
        StrategyConfig(
            enabled=config.strategy.enabled,
            universe=config.strategy.universe,
            dte_min=config.strategy.dte_min,
            dte_max=config.strategy.dte_max,
            short_delta_min=short_delta_min
            if short_delta_min is not None
            else config.strategy.short_delta_min,
            short_delta_max=short_delta_max
            if short_delta_max is not None
            else config.strategy.short_delta_max,
            spread_widths=spread_widths if spread_widths is not None else config.strategy.spread_widths,
            min_credit_ratio=min_credit_ratio
            if min_credit_ratio is not None
            else config.strategy.min_credit_ratio,
            profit_take_ratio=config.strategy.profit_take_ratio,
            loss_multiple=config.strategy.loss_multiple,
            close_dte=config.strategy.close_dte,
        )
    )


def _build_risk_manager(
    config,
    *,
    max_position_loss: float | None = None,
    max_open_risk: float | None = None,
    max_open_positions: int | None = None,
    kill_switch_active: bool | None = None,
) -> RiskManager:
    return RiskManager(
        AccountRiskLimits(
            max_position_loss=max_position_loss
            if max_position_loss is not None
            else config.account.max_position_loss,
            max_open_risk=max_open_risk if max_open_risk is not None else config.account.max_open_risk,
            max_open_positions=max_open_positions
            if max_open_positions is not None
            else config.account.max_open_positions,
            max_daily_loss=config.account.max_daily_loss,
            max_weekly_loss=config.account.max_weekly_loss,
            shutdown_equity=config.account.shutdown_equity,
            kill_switch_active=kill_switch_active
            if kill_switch_active is not None
            else config.execution.kill_switch_active,
        )
    )


def _build_scanner_config(
    journal: Journal,
    *,
    now: datetime,
    account_equity: float,
    max_quote_age_seconds: int,
    max_bid_ask_width: float,
    open_risk: float = 0.0,
    open_positions: int = 0,
) -> ScannerConfig:
    pnl_totals = realized_pnl_totals(journal, today=now.date())
    return ScannerConfig(
        now=now,
        account_equity=account_equity,
        open_risk=open_risk,
        open_positions=open_positions,
        realized_pnl_today=pnl_totals.today,
        realized_pnl_week=pnl_totals.week,
        max_quote_age_seconds=max_quote_age_seconds,
        max_bid_ask_width=max_bid_ask_width,
    )


def _build_order_ticket_preview(
    decisions, *, starting_equity: float
) -> OpeningCreditSpreadTicket | None:
    for decision in decisions:
        if decision.action == "would_trade" and decision.candidate is not None:
            return build_opening_credit_spread_ticket(
                decision.candidate,
                starting_equity=starting_equity,
            )
    return None


def _quote_width_by_option_symbol(quotes: list[OptionQuote]) -> dict[str, float]:
    return {quote.option_symbol: quote.bid_ask_width for quote in quotes if quote.option_symbol}


def _candidate_payload(candidate) -> dict[str, object]:
    return {
        "strategy": candidate.strategy_label,
        "symbol": candidate.symbol,
        "expiration": candidate.expiration,
        "dte": candidate.dte,
        "short_strike": candidate.short_strike,
        "long_strike": candidate.long_strike,
        "short_option_symbol": candidate.short_option_symbol,
        "long_option_symbol": candidate.long_option_symbol,
        "short_delta": candidate.short_delta,
        "credit": candidate.credit,
        "max_loss": candidate.spread.max_loss,
        "credit_ratio": candidate.credit_ratio,
    }


def _print_order_ticket_preview(ticket: OpeningCreditSpreadTicket | None) -> None:
    if ticket is None:
        console.print("No would_trade decision available for order ticket preview.")
        return

    table = Table(title="Opening Order Ticket Preview — Dry Run Only")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Strategy", ticket.strategy)
    table.add_row("Symbol", ticket.symbol)
    table.add_row("Order Type", ticket.order_type)
    table.add_row("Net Price Effect", ticket.net_price_effect)
    table.add_row("Net Credit", f"{ticket.net_credit:.2f}")
    table.add_row("Max Loss", f"{ticket.max_loss:.2f}")
    table.add_row("Account Risk", ticket.account_risk_percent)
    table.add_row("Safety Status", ticket.safety_status)
    table.add_row("Submission Allowed", str(ticket.submission_allowed))
    for index, leg in enumerate(ticket.legs, start=1):
        table.add_row(f"Leg {index}", f"{leg.action} {leg.quantity} {leg.option_symbol}")
    console.print(table)


def _print_closing_order_ticket_preview(ticket: ClosingCreditSpreadTicket) -> None:
    table = Table(title="Closing Order Ticket Preview — Dry Run Only")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Strategy", ticket.strategy)
    table.add_row("Symbol", ticket.symbol)
    table.add_row("Order Type", ticket.order_type)
    table.add_row("Net Price Effect", ticket.net_price_effect)
    table.add_row("Estimated Debit", f"{ticket.estimated_debit:.2f}")
    table.add_row("Safety Status", ticket.safety_status)
    table.add_row("Submission Allowed", str(ticket.submission_allowed))
    for index, leg in enumerate(ticket.legs, start=1):
        table.add_row(f"Leg {index}", f"{leg.action} {leg.quantity} {leg.option_symbol}")
    console.print(table)


def _balance_value(balance: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = balance.get(key)
        if value is None:
            continue
        try:
            return round(float(value), 2)
        except (TypeError, ValueError):
            continue
    return None


def _balance_snapshot_payload(balance: dict[str, Any]) -> dict[str, Any]:
    return {
        "net_liquidating_value": _balance_value(
            balance,
            "net_liquidating_value",
            "net-liquidating-value",
            "net_liq",
            "net-liq",
        ),
        "cash_balance": _balance_value(balance, "cash_balance", "cash-balance"),
        "option_buying_power": _balance_value(
            balance,
            "option_buying_power",
            "option-buying-power",
            "derivative_buying_power",
            "derivative-buying-power",
        ),
        "raw_keys": sorted(str(key) for key in balance.keys()),
    }


@app.command("account-snapshot")
def account_snapshot(
    journal_path: Path = typer.Option(Path("data/journal.jsonl"), help="Audit journal JSONL path."),
) -> None:
    """Fetch tastytrade account balances read-only and write a dashboard journal snapshot."""
    client = build_tastytrade_client()
    authenticate_client(client)
    balance = client.get_balance()
    payload = _balance_snapshot_payload(balance)
    Journal(journal_path).append(
        JournalEvent(
            event_type="account_balance_snapshot",
            decision="recorded",
            reason="read_only_dashboard_refresh",
            payload=payload,
        )
    )
    console.print("Account balance snapshot recorded")
    if payload["net_liquidating_value"] is not None:
        console.print(f"Net liquidating value: ${payload['net_liquidating_value']:,.2f}")
    if payload["cash_balance"] is not None:
        console.print(f"Cash balance: ${payload['cash_balance']:,.2f}")
    if payload["option_buying_power"] is not None:
        console.print(f"Option buying power: ${payload['option_buying_power']:,.2f}")
    console.print("No orders were placed; account-snapshot is read-only.")


@app.command("dashboard-refresh")
def dashboard_refresh(
    symbol: str = typer.Option("SPY", help="Underlying symbol to scan for dashboard candidates."),
    journal_path: Path = typer.Option(Path("data/journal.jsonl"), help="Audit journal JSONL path."),
) -> None:
    """Refresh dashboard journal data using read-only account and scanner calls."""
    account_snapshot(journal_path=journal_path)
    live_dry_run(
        symbol=symbol.upper(),
        dte_min=30,
        dte_max=45,
        max_contracts=100,
        max_quote_age_seconds=120,
        max_bid_ask_width=0.20,
        spread_width=None,
        min_credit_ratio=None,
        short_delta_min=None,
        short_delta_max=None,
        max_position_loss=None,
        max_open_risk=None,
        max_open_positions=None,
        preset=None,
        best_only=True,
        ticket_preview=True,
        submit_open=False,
        i_understand_live_order=False,
        confirm_symbol=None,
        max_entry_leg_bid_ask_width=None,
        journal_path=journal_path,
        max_results=10,
    )
    console.print("Dashboard data refresh complete")
    console.print("No orders were placed; dashboard-refresh is read-only.")


@app.command("option-chain")
def option_chain(
    symbol: str = typer.Argument("SPY"), dte_min: int = 30, dte_max: int = 45, puts_only: bool = True
) -> None:
    """Fetch tastytrade nested option chain contracts read-only."""
    client = build_tastytrade_client()
    authenticate_client(client)
    items = client.get_nested_option_chain(symbol)
    contracts = parse_nested_option_chain(
        items,
        option_type="put" if puts_only else None,
        dte_min=dte_min,
        dte_max=dte_max,
    )
    if not contracts:
        console.print("No option contracts returned for filters.")
        return
    table = Table(title=f"{symbol.upper()} Option Chain Contracts")
    table.add_column("Expiration")
    table.add_column("DTE")
    table.add_column("Type")
    table.add_column("Strike")
    table.add_column("Symbol")
    table.add_column("Streamer")
    for contract in contracts[:50]:
        table.add_row(
            contract.expiration.isoformat(),
            str(contract.dte),
            contract.option_type,
            f"{contract.strike:.2f}",
            contract.option_symbol,
            contract.streamer_symbol,
        )
    console.print(table)
    console.print(f"Showing {min(len(contracts), 50)} of {len(contracts)} matching contracts.")
    console.print("Read-only chain metadata only: no orders were placed.")


@app.command("live-dry-run")
def live_dry_run(
    symbol: str = typer.Argument("SPY"),
    dte_min: int = 30,
    dte_max: int = 45,
    max_contracts: int = 100,
    max_quote_age_seconds: int = 120,
    max_bid_ask_width: float = 0.20,
    spread_width: list[int] | None = typer.Option(
        None, "--spread-width", help="Allowed spread width. Repeat for multiple widths."
    ),
    min_credit_ratio: float | None = typer.Option(
        None, help="Research-only minimum credit / spread width override."
    ),
    short_delta_min: float | None = typer.Option(None, help="Research-only short delta minimum override."),
    short_delta_max: float | None = typer.Option(None, help="Research-only short delta maximum override."),
    max_position_loss: float | None = typer.Option(
        None, help="Research-only max position loss override."
    ),
    max_open_risk: float | None = typer.Option(None, help="Research-only max open risk override."),
    max_open_positions: int | None = typer.Option(
        None, help="Research-only max open positions override."
    ),
    preset: str | None = typer.Option(
        None, help="Research preset. Currently supported: five-wide-research."
    ),
    best_only: bool = typer.Option(False, help="Show only the highest-ranked decision."),
    ticket_preview: bool = typer.Option(False, help="Show a non-submitting order ticket preview for the best would_trade decision."),
    submit_open: bool = typer.Option(False, help="Submit the best would_trade opening order only after all live confirmations pass."),
    i_understand_live_order: bool = typer.Option(False, help="Required explicit acknowledgement for --submit-open."),
    confirm_symbol: str | None = typer.Option(None, help="Required with --submit-open; must exactly match SYMBOL."),
    max_entry_leg_bid_ask_width: float | None = typer.Option(None, help="Optional live-submit guard; refuse if either entry leg bid/ask width exceeds this cap."),
    journal_path: Path = typer.Option(Path("data/journal.jsonl"), help="Audit journal JSONL path."),
    max_results: int = typer.Option(50, help="Maximum decisions to display."),
) -> None:
    """Run dry-run scanner against tastytrade REST market data without placing orders."""
    if submit_open:
        if not i_understand_live_order:
            raise typer.BadParameter("--submit-open requires --i-understand-live-order")
        if confirm_symbol is None or confirm_symbol.upper() != symbol.upper():
            raise typer.BadParameter("--submit-open requires --confirm-symbol to match SYMBOL exactly")
        if max_entry_leg_bid_ask_width is not None and max_entry_leg_bid_ask_width <= 0:
            raise typer.BadParameter("--max-entry-leg-bid-ask-width must be positive")

    config = load_config()
    client = build_tastytrade_client()
    authenticate_client(client)

    chain_items = client.get_nested_option_chain(symbol)
    contracts = parse_nested_option_chain(chain_items, option_type="put", dte_min=dte_min, dte_max=dte_max)
    if not contracts:
        console.print("No option contracts returned for filters.")
        return
    selected_contracts = contracts[:max_contracts]
    market_items = client.get_equity_option_market_data([contract.option_symbol for contract in selected_contracts])
    quotes = parse_equity_option_market_data(market_items, selected_contracts)
    if not quotes:
        console.print("No usable bid/ask/delta quotes returned for selected contracts.")
        return

    overrides = _apply_live_dry_run_preset(
        preset=preset,
        spread_width=spread_width,
        min_credit_ratio=min_credit_ratio,
        short_delta_min=short_delta_min,
        short_delta_max=short_delta_max,
        max_position_loss=max_position_loss,
        max_open_risk=max_open_risk,
        max_open_positions=max_open_positions,
    )
    now = datetime.now(timezone.utc)
    strategy = _build_strategy(
        config,
        min_credit_ratio=overrides["min_credit_ratio"],
        spread_widths=overrides["spread_width"],
        short_delta_min=overrides["short_delta_min"],
        short_delta_max=overrides["short_delta_max"],
    )
    journal = Journal(journal_path)
    risk_manager = _build_risk_manager(
        config,
        max_position_loss=overrides["max_position_loss"],
        max_open_risk=overrides["max_open_risk"],
        max_open_positions=overrides["max_open_positions"],
        kill_switch_active=_effective_kill_switch_active(config, journal),
    )
    scanner = DryRunScanner(strategy=strategy, risk_manager=risk_manager, journal=journal)
    decisions = scanner.scan(
        quotes,
        config=_build_scanner_config(
            journal,
            now=now,
            account_equity=config.account.starting_equity,
            max_quote_age_seconds=max_quote_age_seconds,
            max_bid_ask_width=max_bid_ask_width,
        ),
    )
    if not decisions:
        console.print("No spread candidates passed quote/candidate construction filters.")
        diagnostics = diagnose_candidate_construction(
            quotes,
            now=now,
            strategy_config=strategy.config,
            max_quote_age_seconds=max_quote_age_seconds,
            max_bid_ask_width=max_bid_ask_width,
        )
        console.print(f"Quotes parsed: {diagnostics.total_quotes}")
        console.print(f"Base-usable quotes: {diagnostics.usable_quotes}")
        console.print(f"Candidate count: {diagnostics.candidate_count}")
        console.print(
            "Quote age seconds: "
            f"min={diagnostics.quote_age_seconds['min']}, "
            f"median={diagnostics.quote_age_seconds['median']}, "
            f"max={diagnostics.quote_age_seconds['max']}"
        )
        console.print(
            "Bid/ask width: "
            f"min={diagnostics.bid_ask_widths['min']}, "
            f"median={diagnostics.bid_ask_widths['median']}, "
            f"max={diagnostics.bid_ask_widths['max']}"
        )
        if diagnostics.newest_quote_time is not None:
            console.print(f"Newest quote time: {diagnostics.newest_quote_time.isoformat()}")
            console.print(f"Oldest quote time: {diagnostics.oldest_quote_time.isoformat()}")
        if diagnostics.rejection_counts:
            table = Table(title="Candidate Construction Diagnostics")
            table.add_column("Reason")
            table.add_column("Count")
            for reason, count in sorted(diagnostics.rejection_counts.items()):
                table.add_row(reason, str(count))
            console.print(table)
        console.print(
            "Try widening filters, for example: --dte-min 1 --dte-max 90 --max-contracts 500 "
            "--max-quote-age-seconds 86400 --max-bid-ask-width 1.00"
        )
        return

    display_decisions = _rank_decisions(decisions)
    if best_only:
        display_decisions = display_decisions[:1]

    table = Table(title=f"{symbol.upper()} Live REST Dry Run Decisions")
    table.add_column("Action")
    table.add_column("Reason")
    table.add_column("Strategy")
    table.add_column("Expiration")
    table.add_column("DTE")
    table.add_column("Short")
    table.add_column("Long")
    table.add_column("Short Symbol")
    table.add_column("Long Symbol")
    table.add_column("Width")
    table.add_column("Delta")
    table.add_column("Credit")
    table.add_column("Credit %")
    table.add_column("Max Loss")
    table.add_column("Acct Risk %")
    for decision in display_decisions[:max_results]:
        table.add_row(*_format_decision_row(decision, starting_equity=config.account.starting_equity))
    console.print(table)
    if ticket_preview:
        _print_order_ticket_preview(
            _build_order_ticket_preview(display_decisions, starting_equity=config.account.starting_equity)
        )
    if submit_open:
        if _effective_kill_switch_active(config, journal):
            raise typer.BadParameter("kill_switch_active")
        if _has_unresolved_open_order(journal):
            raise typer.BadParameter("submit-open blocked: unresolved live opening order exists; run reconcile-submitted-orders")
        live_positions = client.get_positions()
        live_symbols = _position_symbols(live_positions)
        if live_symbols:
            raise typer.BadParameter(
                f"submit-open blocked: broker has live positions: {', '.join(sorted(live_symbols))}"
            )
        selected_decision = next(
            (decision for decision in _rank_decisions(decisions) if decision.action == "would_trade" and decision.candidate is not None),
            None,
        )
        if selected_decision is None or selected_decision.candidate is None:
            raise typer.BadParameter("submit-open requires a would_trade decision")
        selected_ticket = build_opening_credit_spread_ticket(
            selected_decision.candidate,
            starting_equity=config.account.starting_equity,
        )
        if max_entry_leg_bid_ask_width is not None:
            widths = _quote_width_by_option_symbol(quotes)
            for leg in selected_ticket.legs:
                width = widths.get(leg.option_symbol)
                if width is None:
                    raise typer.BadParameter(f"missing bid/ask width for entry leg {leg.option_symbol}")
                if width > max_entry_leg_bid_ask_width:
                    raise typer.BadParameter(
                        f"entry leg bid/ask width {width:.2f} exceeds max entry leg bid/ask width {max_entry_leg_bid_ask_width:.2f}"
                    )
        order_payload = build_tastytrade_opening_order_payload(selected_ticket)
        order_response = client.submit_order_payload(order_payload, approved=True)
        journal.append(
            JournalEvent(
                event_type="live_open_order_submitted",
                symbol=symbol.upper(),
                decision="submitted",
                reason=selected_decision.reason,
                payload={
                    "candidate": _candidate_payload(selected_decision.candidate),
                    "order_payload": order_payload,
                    "order_response": order_response,
                },
            )
        )
        order = order_response.get("order", {}) if isinstance(order_response, dict) else {}
        order_id = order.get("id", "unknown") if isinstance(order, dict) else "unknown"
        console.print("LIVE OPEN ORDER SUBMITTED")
        console.print(f"Order id: {order_id}")
    console.print(f"Scanned {len(quotes)} option quotes and produced {len(decisions)} decisions.")
    if submit_open:
        console.print("A live opening order submission was attempted after explicit confirmations.")
    else:
        console.print("Dry run only: no orders were placed.")


def _is_us_market_hours(now: datetime | None = None) -> bool:
    """Return True during the regular NYSE/Nasdaq weekday session, 9:30-16:00 ET."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    new_york_now = current.astimezone(ZoneInfo("America/New_York"))
    if new_york_now.weekday() >= 5:
        return False
    minutes_since_midnight = new_york_now.hour * 60 + new_york_now.minute
    market_open = 9 * 60 + 30
    market_close = 16 * 60
    return market_open <= minutes_since_midnight < market_close


@app.command("scheduler")
def scheduler(
    symbol: str = typer.Option("SPY", help="Underlying symbol to scan on each scheduler cycle."),
    mode: str = typer.Option("dry-run", help="Scheduler mode. Only dry-run is supported."),
    interval_seconds: int = typer.Option(300, help="Seconds between cycles when --cycles is greater than 1 or 0."),
    cycles: int = typer.Option(1, help="Number of cycles to run. Use 0 for an indefinite daemon loop."),
    allow_live_submit: bool = typer.Option(False, help="Refused by design; scheduler must not submit live orders."),
    journal_path: Path = typer.Option(Path("data/journal.jsonl"), help="Audit journal JSONL path."),
) -> None:
    """Run a safety-gated dry-run scheduler loop without live order submission."""
    normalized_mode = mode.lower().strip()
    if normalized_mode != "dry-run":
        raise typer.BadParameter("only dry-run scheduler mode is supported")
    if allow_live_submit:
        raise typer.BadParameter("scheduler live submission is not supported; run live-dry-run --submit-open manually")
    if interval_seconds <= 0:
        raise typer.BadParameter("--interval-seconds must be positive")
    if cycles < 0:
        raise typer.BadParameter("--cycles must be zero or positive")

    config = load_config()
    journal = Journal(journal_path)
    cycle_label_total = "∞" if cycles == 0 else str(cycles)
    console.print("Scheduler mode: dry-run")
    console.print("Scheduler safety: submit_open=False")
    console.print(f"Symbol: {symbol.upper()}")
    console.print(f"Cycles: {cycle_label_total}")
    console.print(f"Interval seconds: {interval_seconds}")
    console.print("No live orders will be submitted by scheduler mode.")

    cycle_number = 0
    while cycles == 0 or cycle_number < cycles:
        cycle_number += 1
        console.print(f"Scheduler cycle {cycle_number}/{cycle_label_total}")
        market_hours_active = _is_us_market_hours()
        console.print(f"Market hours active: {market_hours_active}")
        if not market_hours_active:
            console.print("Skipping scheduler cycle because market is closed.")
        else:
            kill_switch_active = _effective_kill_switch_active(config, journal)
            console.print(f"Kill switch active: {kill_switch_active}")
            if kill_switch_active:
                console.print("Skipping scheduler cycle because kill switch is active.")
            else:
                live_dry_run(
                    symbol=symbol.upper(),
                    dte_min=30,
                    dte_max=45,
                    max_contracts=100,
                    max_quote_age_seconds=120,
                    max_bid_ask_width=0.20,
                    spread_width=None,
                    min_credit_ratio=None,
                    short_delta_min=None,
                    short_delta_max=None,
                    max_position_loss=None,
                    max_open_risk=None,
                    max_open_positions=None,
                    preset=None,
                    best_only=True,
                    ticket_preview=True,
                    submit_open=False,
                    i_understand_live_order=False,
                    confirm_symbol=None,
                    max_entry_leg_bid_ask_width=None,
                    journal_path=journal_path,
                    max_results=10,
                )
        if cycles == 0 or cycle_number < cycles:
            time.sleep(interval_seconds)


@app.command("dry-run-demo")
def dry_run_demo() -> None:
    """Run scanner on built-in sample quotes without placing orders."""
    config = load_config()
    now = datetime.now(timezone.utc)
    expiration = (now + timedelta(days=40)).date()
    quotes = [
        OptionQuote(
            symbol="SPY",
            expiration=expiration,
            option_type="put",
            strike=100.0,
            delta=-0.20,
            bid=0.30,
            ask=0.34,
            quote_time=now,
        ),
        OptionQuote(
            symbol="SPY",
            expiration=expiration,
            option_type="put",
            strike=99.0,
            delta=-0.10,
            bid=0.02,
            ask=0.04,
            quote_time=now,
        ),
    ]
    strategy = _build_strategy(config)
    risk_manager = _build_risk_manager(config)
    scanner = DryRunScanner(strategy=strategy, risk_manager=risk_manager, journal=Journal())
    decisions = scanner.scan(
        quotes,
        config=ScannerConfig(now=now, account_equity=config.account.starting_equity),
    )
    if not decisions:
        console.print("No candidates found.")
        return
    table = Table(title="Dry Run Scanner Decisions")
    table.add_column("Action")
    table.add_column("Reason")
    table.add_column("Symbol")
    table.add_column("Strategy")
    table.add_column("Short")
    table.add_column("Long")
    table.add_column("Credit")
    table.add_column("Max Loss")
    for decision in decisions:
        candidate = decision.candidate
        table.add_row(
            decision.action,
            decision.reason,
            candidate.symbol if candidate else "",
            candidate.strategy_label if candidate else "",
            str(candidate.short_strike) if candidate else "",
            str(candidate.long_strike) if candidate else "",
            f"{candidate.credit:.2f}" if candidate else "",
            f"{candidate.spread.max_loss:.2f}" if candidate else "",
        )
    console.print(table)
    console.print("Dry run only: no orders were placed.")


def _build_manual_trade_event(
    *,
    symbol: str,
    strategy: str,
    expiration: str,
    short_option_symbol: str,
    long_option_symbol: str,
    short_strike: float,
    long_strike: float,
    quantity: int,
    credit: float,
    starting_equity: float,
) -> JournalEvent:
    if quantity <= 0:
        raise typer.BadParameter("quantity must be positive")
    if credit <= 0:
        raise typer.BadParameter("credit must be positive")
    if short_strike <= long_strike:
        raise typer.BadParameter("put credit spread short strike must be above long strike")
    if not short_option_symbol.strip() or not long_option_symbol.strip():
        raise typer.BadParameter("both option symbols are required")
    date.fromisoformat(expiration)

    width = round(short_strike - long_strike, 4)
    max_profit = round(credit * 100 * quantity, 2)
    max_loss = round((width - credit) * 100 * quantity, 2)
    breakeven = round(short_strike - credit, 2)
    profit_target_debit = round(credit * 0.50, 2)
    loss_exit_debit = round(credit * 2.0, 2)
    account_risk_percent = round((max_loss / starting_equity) * 100, 2) if starting_equity > 0 else 0.0

    return JournalEvent(
        event_type="manual_live_trade_entered",
        symbol=symbol.upper(),
        decision="entered_manually",
        reason="manual_tastytrade_entry",
        payload={
            "symbol": symbol.upper(),
            "strategy": strategy,
            "expiration": expiration,
            "short_option_symbol": short_option_symbol,
            "long_option_symbol": long_option_symbol,
            "short_strike": short_strike,
            "long_strike": long_strike,
            "quantity": quantity,
            "width": width,
            "credit": credit,
            "max_profit": max_profit,
            "max_loss": max_loss,
            "breakeven": breakeven,
            "account_risk_percent": account_risk_percent,
            "profit_target_debit": profit_target_debit,
            "loss_exit_debit": loss_exit_debit,
            "source": "manual_tastytrade_entry",
            "bot_submission": False,
            "submission_allowed": False,
        },
    )


@app.command("record-manual-trade")
def record_manual_trade(
    symbol: str = typer.Option(..., help="Underlying symbol, e.g. SPY."),
    strategy: str = typer.Option("Put Credit Spread", help="Human-readable strategy label."),
    expiration: str = typer.Option(..., help="Option expiration date, YYYY-MM-DD."),
    short_option_symbol: str = typer.Option(..., help="Exact tastytrade short leg symbol."),
    long_option_symbol: str = typer.Option(..., help="Exact tastytrade long leg symbol."),
    short_strike: float = typer.Option(..., help="Short option strike."),
    long_strike: float = typer.Option(..., help="Long option strike."),
    quantity: int = typer.Option(1, help="Spread quantity."),
    credit: float = typer.Option(..., help="Opening credit per spread, e.g. 1.00."),
    starting_equity: float = typer.Option(3000.0, help="Account equity for risk percentage."),
    journal_path: Path = typer.Option(Path("data/journal.jsonl"), help="Audit journal JSONL path."),
) -> None:
    """Record a manually entered live trade in the local journal without placing orders."""
    event = _build_manual_trade_event(
        symbol=symbol,
        strategy=strategy,
        expiration=expiration,
        short_option_symbol=short_option_symbol,
        long_option_symbol=long_option_symbol,
        short_strike=short_strike,
        long_strike=long_strike,
        quantity=quantity,
        credit=credit,
        starting_equity=starting_equity,
    )
    Journal(journal_path).append(event)
    payload = event.payload
    console.print("Manual trade recorded in journal")
    console.print(f"Journal path: {journal_path}")
    console.print(f"Strategy: {payload['strategy']}")
    console.print(f"Symbol: {payload['symbol']}")
    console.print(f"Expiration: {payload['expiration']}")
    console.print(f"Short leg: sell_to_open {payload['quantity']} {payload['short_option_symbol']}")
    console.print(f"Long leg: buy_to_open {payload['quantity']} {payload['long_option_symbol']}")
    console.print(f"Credit: ${payload['credit']:.2f}")
    console.print(f"Max profit: ${payload['max_profit']:.2f}")
    console.print(f"Max loss: ${payload['max_loss']:.2f}")
    console.print(f"Breakeven: {payload['breakeven']:.2f}")
    console.print(f"Profit target debit: ${payload['profit_target_debit']:.2f}")
    console.print(f"Loss exit debit: ${payload['loss_exit_debit']:.2f}")
    console.print(f"Account risk: {payload['account_risk_percent']:.2f}%")
    console.print(f"Bot submission: {payload['bot_submission']}")
    console.print("No orders were placed; this command only records the manual trade.")


def _manual_position_id(event: JournalEvent) -> str:
    return f"manual:{event.symbol}:{event.payload['expiration']}"


def _position_id_from_open_event(event: JournalEvent) -> str:
    position_id = event.payload.get("position_id")
    if isinstance(position_id, str) and position_id:
        return position_id
    if event.event_type == "manual_live_trade_entered":
        return _manual_position_id(event)
    order_id = str(event.payload.get("order_id", "")).strip()
    suffix = f":{order_id}" if order_id else ""
    return f"bot:{event.symbol}:{event.payload['expiration']}{suffix}"


def _closed_manual_position_ids(journal: Journal) -> set[str]:
    closed_ids = set()
    for event in journal.read_recent(limit=1000):
        if event.event_type not in {"manual_live_trade_closed", "live_close_order_filled"}:
            continue
        position_id = event.payload.get("position_id")
        if isinstance(position_id, str) and position_id:
            closed_ids.add(position_id)
    return closed_ids


def _latest_manual_trade_event(journal: Journal, *, symbol: str) -> JournalEvent | None:
    closed_ids = _closed_manual_position_ids(journal)
    for event in journal.read_recent(limit=1000):
        if event.event_type not in {"manual_live_trade_entered", "live_open_order_filled"}:
            continue
        if event.symbol.upper() != symbol.upper():
            continue
        if _position_id_from_open_event(event) in closed_ids:
            continue
        return event
    return None


def _position_quantity(position: dict) -> float:
    try:
        return float(position.get("quantity", 0))
    except (TypeError, ValueError):
        return 0.0


def _position_symbols(positions: list[dict]) -> set[str]:
    return {str(position.get("symbol", "")) for position in positions if _position_quantity(position) != 0}


def _quote_bid_ask_by_symbol(items: list[dict]) -> dict[str, tuple[float, float, float]]:
    quotes = {}
    for item in items:
        try:
            bid = float(item["bid"])
            ask = float(item["ask"])
            mark = _quote_mark(item, bid=bid, ask=ask)
            quotes[str(item["symbol"])] = (bid, ask, mark)
        except (KeyError, TypeError, ValueError):
            continue
    return quotes


def _quote_mark(item: dict, *, bid: float, ask: float) -> float:
    for key in ("mark", "mid"):
        value = item.get(key)
        if value not in (None, ""):
            return float(value)
    return round((bid + ask) / 2, 4)


def _managed_position_from_manual_event(event: JournalEvent) -> ManagedPosition:
    payload = event.payload
    expiration = date.fromisoformat(str(payload["expiration"]))
    opened_at = event.created_at.date()
    opening_credit = float(payload.get("opening_credit", payload.get("credit", 0)))
    return ManagedPosition(
        position_id=_position_id_from_open_event(event),
        symbol=event.symbol,
        spread=CreditSpread(
            short_strike=float(payload["short_strike"]),
            long_strike=float(payload["long_strike"]),
            credit=opening_credit,
            quantity=int(payload.get("quantity", 1)),
        ),
        expiration=expiration,
        opened_at=opened_at,
        opening_credit=opening_credit,
    )


def _has_submitted_close_order(journal: Journal, *, position_id: str) -> bool:
    for event in journal.read_recent(limit=1000):
        if event.event_type != "live_close_order_submitted":
            continue
        if event.payload.get("position_id") == position_id:
            return True
    return False


def _has_unresolved_open_order(journal: Journal) -> bool:
    terminal_ids = _terminal_reconciled_order_ids(journal)
    for event in journal.read_recent(limit=1000):
        if event.event_type != "live_open_order_submitted":
            continue
        order_id = _order_id_from_submission_event(event)
        if not order_id or order_id not in terminal_ids:
            return True
    return False


def _order_id_from_submission_event(event: JournalEvent) -> str:
    response = event.payload.get("order_response", {})
    if not isinstance(response, dict):
        return ""
    order = response.get("order", response)
    if not isinstance(order, dict):
        return ""
    return str(order.get("id", "")).strip()


def _order_dict(order_response: dict) -> dict:
    order = order_response.get("order", order_response)
    return order if isinstance(order, dict) else {}


def _order_status_decision(status: str) -> str:
    normalized = status.lower().replace(" ", "_").replace("-", "_")
    if normalized in {"filled", "executed"}:
        return "filled"
    if normalized in {"cancelled", "canceled", "rejected", "expired"}:
        return "terminal"
    return "working"


def _float_from_order(order: dict, keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = order.get(key)
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _terminal_reconciled_order_ids(journal: Journal) -> set[str]:
    terminal_ids = set()
    for event in journal.read_recent(limit=1000):
        if event.event_type not in {
            "live_close_order_filled",
            "live_close_order_reconciled",
            "live_open_order_filled",
            "live_open_order_reconciled",
        }:
            continue
        order_id = event.payload.get("order_id")
        if not isinstance(order_id, str) or not order_id:
            continue
        status = str(event.payload.get("status", event.decision)).lower()
        if event.event_type in {"live_close_order_filled", "live_open_order_filled"} or status in {
            "filled",
            "cancelled",
            "canceled",
            "rejected",
            "expired",
        }:
            terminal_ids.add(order_id)
    return terminal_ids


def _submitted_order_events_to_reconcile(journal: Journal) -> list[JournalEvent]:
    terminal_ids = _terminal_reconciled_order_ids(journal)
    seen_order_ids: set[str] = set()
    events: list[JournalEvent] = []
    for event in journal.read_recent(limit=1000):
        if event.event_type not in {"live_close_order_submitted", "live_open_order_submitted"}:
            continue
        order_id = _order_id_from_submission_event(event)
        if not order_id or order_id in terminal_ids or order_id in seen_order_ids:
            continue
        seen_order_ids.add(order_id)
        events.append(event)
    return list(reversed(events))


def _opening_event_by_position_id(journal: Journal) -> dict[str, JournalEvent]:
    openings = {}
    for event in journal.read_recent(limit=1000):
        if event.event_type not in {"manual_live_trade_entered", "live_open_order_filled"}:
            continue
        openings.setdefault(_position_id_from_open_event(event), event)
    return openings


@app.command("reconcile-submitted-orders")
def reconcile_submitted_orders(
    journal_path: Path = typer.Option(Path("data/journal.jsonl"), help="Audit journal JSONL path."),
) -> None:
    """Fetch status for submitted live orders and journal working/fill/terminal state."""
    journal = Journal(journal_path)
    submissions = _submitted_order_events_to_reconcile(journal)
    if not submissions:
        console.print("No submitted orders need reconciliation.")
        return

    client = build_tastytrade_client()
    authenticate_client(client)
    openings = _opening_event_by_position_id(journal)
    console.print("Submitted order reconciliation")
    for submission in submissions:
        order_id = _order_id_from_submission_event(submission)
        order_response = client.get_order(order_id)
        order = _order_dict(order_response)
        status = str(order.get("status", "unknown"))
        decision = _order_status_decision(status)
        filled_quantity = _float_from_order(order, ("filled-quantity", "filled_quantity", "quantity-filled"))
        fill_price = _float_from_order(
            order,
            ("average-fill-price", "avg-fill-price", "filled-price", "price"),
        )
        console.print(f"Order {order_id}: {status}")

        if submission.event_type == "live_open_order_submitted":
            candidate = submission.payload.get("candidate", {})
            candidate = candidate if isinstance(candidate, dict) else {}
            position_id = f"bot:{submission.symbol}:{candidate.get('expiration', '')}:{order_id}"
            journal.append(
                JournalEvent(
                    event_type="live_open_order_reconciled",
                    symbol=submission.symbol,
                    decision=decision,
                    reason=f"order_status_{status.lower()}",
                    payload={
                        "position_id": position_id,
                        "order_id": order_id,
                        "status": status,
                        "filled_quantity": filled_quantity,
                        "fill_price": fill_price,
                        "order_response": order_response,
                    },
                )
            )
            if decision != "filled":
                continue
            if fill_price is None:
                console.print("Filled opening order could not be recorded: missing fill price.")
                continue
            quantity = int(candidate.get("quantity", filled_quantity or 1))
            opening_credit = round(fill_price, 2)
            journal.append(
                JournalEvent(
                    event_type="live_open_order_filled",
                    symbol=submission.symbol,
                    decision="filled",
                    reason="order_status_filled",
                    payload={
                        "position_id": position_id,
                        "order_id": order_id,
                        "status": status,
                        "strategy": candidate.get("strategy", "Put Credit Spread"),
                        "expiration": candidate["expiration"],
                        "short_option_symbol": candidate.get("short_option_symbol", ""),
                        "long_option_symbol": candidate.get("long_option_symbol", ""),
                        "short_strike": candidate.get("short_strike"),
                        "long_strike": candidate.get("long_strike"),
                        "quantity": quantity,
                        "opening_credit": opening_credit,
                        "credit": opening_credit,
                        "max_loss": candidate.get("max_loss"),
                        "source": "bot_open_order_fill",
                        "bot_submission": True,
                    },
                )
            )
            console.print(f"Opening fill recorded: ${opening_credit:.2f}")
            continue

        position_id = str(submission.payload.get("position_id", ""))
        journal.append(
            JournalEvent(
                event_type="live_close_order_reconciled",
                symbol=submission.symbol,
                decision=decision,
                reason=f"order_status_{status.lower()}",
                payload={
                    "position_id": position_id,
                    "order_id": order_id,
                    "status": status,
                    "filled_quantity": filled_quantity,
                    "fill_price": fill_price,
                    "order_response": order_response,
                },
            )
        )

        if decision != "filled":
            continue
        opening = openings.get(position_id)
        if opening is None or fill_price is None:
            console.print("Filled order could not be converted to a close event: missing opening trade or fill price.")
            continue
        payload = opening.payload
        quantity = int(payload.get("quantity", 1))
        opening_credit = float(payload.get("opening_credit", payload.get("credit", 0)))
        close_debit = round(fill_price, 2)
        realized_pnl = round((opening_credit - close_debit) * 100 * quantity, 2)
        journal.append(
            JournalEvent(
                event_type="live_close_order_filled",
                symbol=submission.symbol,
                decision="filled",
                reason="order_status_filled",
                payload={
                    "position_id": position_id,
                    "order_id": order_id,
                    "status": status,
                    "strategy": payload.get("strategy", "Put Credit Spread"),
                    "expiration": payload["expiration"],
                    "short_option_symbol": payload.get("short_option_symbol", ""),
                    "long_option_symbol": payload.get("long_option_symbol", ""),
                    "quantity": quantity,
                    "opening_credit": opening_credit,
                    "close_debit": close_debit,
                    "realized_pnl": realized_pnl,
                    "source": "bot_close_order_fill",
                    "bot_submission": True,
                },
            )
        )
        console.print(f"Realized P/L: ${realized_pnl:.2f}")


@app.command("manage-live-positions")
def manage_live_positions(
    symbol: str = typer.Option("SPY", help="Underlying symbol to reconcile."),
    today: str | None = typer.Option(None, help="Review date YYYY-MM-DD. Defaults to today UTC."),
    close_preview: bool = typer.Option(False, help="Show a non-submitting close ticket preview when exit action is close."),
    force_close_preview: bool = typer.Option(False, help="Show close preview even when action is hold, for review only."),
    submit_close: bool = typer.Option(False, help="Submit a live close order only when exit action is close and all confirmations are present."),
    i_understand_live_order: bool = typer.Option(False, help="Required explicit acknowledgement for --submit-close."),
    confirm_symbol: str | None = typer.Option(None, help="Required with --submit-close; must exactly match --symbol."),
    max_close_debit: float | None = typer.Option(None, help="Optional live-submit guard; refuse close order if estimated debit exceeds this cap."),
    max_close_leg_bid_ask_width: float | None = typer.Option(None, help="Optional live-submit guard; refuse close order if either leg bid/ask width exceeds this cap."),
    journal_path: Path = typer.Option(Path("data/journal.jsonl"), help="Audit journal JSONL path."),
) -> None:
    """Fetch live positions read-only, match journaled spread, and print exit guidance."""
    journal = Journal(journal_path)
    event = _latest_manual_trade_event(journal, symbol=symbol)
    if event is None:
        raise typer.BadParameter(f"no open manual trade found for {symbol.upper()} in {journal_path}")

    if submit_close:
        if not i_understand_live_order:
            raise typer.BadParameter("--submit-close requires --i-understand-live-order")
        if confirm_symbol is None or confirm_symbol.upper() != symbol.upper():
            raise typer.BadParameter("--submit-close requires --confirm-symbol to match --symbol exactly")
        if max_close_debit is not None and max_close_debit <= 0:
            raise typer.BadParameter("--max-close-debit must be positive")
        if max_close_leg_bid_ask_width is not None and max_close_leg_bid_ask_width <= 0:
            raise typer.BadParameter("--max-close-leg-bid-ask-width must be positive")

    payload = event.payload
    short_symbol = str(payload["short_option_symbol"])
    long_symbol = str(payload["long_option_symbol"])
    expected_symbols = {short_symbol, long_symbol}

    client = build_tastytrade_client()
    authenticate_client(client)
    positions = client.get_positions()
    live_symbols = _position_symbols(positions)
    matched = expected_symbols.issubset(live_symbols)
    unexpected_symbols = sorted(live_symbols - expected_symbols)
    unexpected_live_positions = bool(unexpected_symbols)
    new_entries_blocked = matched or unexpected_live_positions

    console.print("Live position reconciliation")
    console.print(f"Symbol: {symbol.upper()}")
    console.print(f"Matched journaled spread: {matched}")
    console.print(f"Unexpected live positions: {unexpected_live_positions}")
    if unexpected_symbols:
        console.print(f"Unexpected symbols: {', '.join(unexpected_symbols)}")

    if matched:
        market_items = client.get_equity_option_market_data([short_symbol, long_symbol])
        quotes = _quote_bid_ask_by_symbol(market_items)
        if short_symbol not in quotes or long_symbol not in quotes:
            raise typer.BadParameter("missing bid/ask quote for one or more spread legs")
        _short_bid, short_ask, short_mark = quotes[short_symbol]
        long_bid, long_ask, long_mark = quotes[long_symbol]
        short_width = round(short_ask - _short_bid, 2)
        long_width = round(long_ask - long_bid, 2)
        current_debit = round(short_ask - long_bid, 2)
        mark_debit = round(short_mark - long_mark, 2)
        review_date = date.fromisoformat(today) if today is not None else datetime.now(timezone.utc).date()
        position = _managed_position_from_manual_event(event)
        decision = PositionManager(PositionManagerConfig()).evaluate(
            position,
            current_debit=current_debit,
            today=review_date,
        )
        pnl_if_closed_at_mark = position.pnl_if_closed(mark_debit)
        conservative_pnl_if_closed = position.pnl_if_closed(current_debit)
        journal.append(decision.to_journal_event())

        console.print(f"Short leg ask: ${short_ask:.2f}")
        console.print(f"Long leg bid: ${long_bid:.2f}")
        console.print(f"Short leg mark: ${short_mark:.2f}")
        console.print(f"Long leg mark: ${long_mark:.2f}")
        console.print(f"Short leg bid/ask width: ${short_width:.2f}")
        console.print(f"Long leg bid/ask width: ${long_width:.2f}")
        console.print(f"Mark debit to close: ${mark_debit:.2f}")
        console.print(f"P/L if closed: ${pnl_if_closed_at_mark:.2f}")
        console.print(f"Conservative marketable debit to close: ${current_debit:.2f}")
        console.print(f"Conservative P/L if closed: ${conservative_pnl_if_closed:.2f}")
        console.print(f"DTE: {decision.dte}")
        console.print(f"Action: {decision.action}")
        console.print(f"Reason: {decision.reason}")
        ticket = None
        if close_preview or submit_close:
            if decision.action == "close" or (close_preview and force_close_preview and not submit_close):
                ticket = build_closing_credit_spread_ticket(
                    symbol=symbol,
                    strategy=str(payload.get("strategy", "Put Credit Spread")),
                    short_option_symbol=short_symbol,
                    long_option_symbol=long_symbol,
                    quantity=int(payload.get("quantity", 1)),
                    estimated_debit=current_debit,
                )
                _print_closing_order_ticket_preview(ticket)
            elif close_preview:
                console.print("No close preview because action is hold; use --force-close-preview for review only.")

        if submit_close:
            if _effective_kill_switch_active(load_config(), journal):
                raise typer.BadParameter("kill_switch_active")
            if decision.action != "close":
                raise typer.BadParameter("submit-close requires action close; current action is hold")
            if _has_submitted_close_order(journal, position_id=decision.position_id):
                raise typer.BadParameter(
                    f"close order already submitted for position {decision.position_id}"
                )
            if max_close_debit is not None and current_debit > max_close_debit:
                raise typer.BadParameter(
                    f"estimated close debit {current_debit:.2f} exceeds max close debit {max_close_debit:.2f}"
                )
            if max_close_leg_bid_ask_width is not None:
                if short_width > max_close_leg_bid_ask_width:
                    raise typer.BadParameter(
                        f"short leg bid/ask width {short_width:.2f} exceeds max close leg bid/ask width {max_close_leg_bid_ask_width:.2f}"
                    )
                if long_width > max_close_leg_bid_ask_width:
                    raise typer.BadParameter(
                        f"long leg bid/ask width {long_width:.2f} exceeds max close leg bid/ask width {max_close_leg_bid_ask_width:.2f}"
                    )
            if ticket is None:
                ticket = build_closing_credit_spread_ticket(
                    symbol=symbol,
                    strategy=str(payload.get("strategy", "Put Credit Spread")),
                    short_option_symbol=short_symbol,
                    long_option_symbol=long_symbol,
                    quantity=int(payload.get("quantity", 1)),
                    estimated_debit=current_debit,
                )
            order_payload = build_tastytrade_closing_order_payload(ticket)
            order_response = client.submit_order_payload(order_payload, approved=True)
            journal.append(
                JournalEvent(
                    event_type="live_close_order_submitted",
                    symbol=symbol.upper(),
                    decision="submitted",
                    reason=decision.reason,
                    payload={
                        "order_payload": order_payload,
                        "order_response": order_response,
                        "position_id": decision.position_id,
                    },
                )
            )
            order = order_response.get("order", {}) if isinstance(order_response, dict) else {}
            order_id = order.get("id", "unknown") if isinstance(order, dict) else "unknown"
            console.print("LIVE CLOSE ORDER SUBMITTED")
            console.print(f"Order id: {order_id}")
    else:
        journal.append(
            JournalEvent(
                event_type="live_position_reconciliation",
                symbol=symbol.upper(),
                decision="blocked",
                reason="journaled_spread_not_matched" if not unexpected_live_positions else "unexpected_live_positions",
                payload={
                    "expected_symbols": sorted(expected_symbols),
                    "live_symbols": sorted(live_symbols),
                    "unexpected_symbols": unexpected_symbols,
                    "new_entries_blocked": new_entries_blocked,
                },
            )
        )

    console.print(f"New entries blocked: {new_entries_blocked}")
    if submit_close:
        console.print("A live close order submission was attempted after explicit confirmations.")
    else:
        console.print("No orders were placed; this command only performs read-only reconciliation and guidance.")


@app.command("record-manual-close")
def record_manual_close(
    symbol: str = typer.Option(..., help="Underlying symbol, e.g. SPY."),
    close_debit: float = typer.Option(..., help="Filled debit paid to close per spread, e.g. 0.45."),
    journal_path: Path = typer.Option(Path("data/journal.jsonl"), help="Audit journal JSONL path."),
) -> None:
    """Record a manually closed spread fill in the local journal without placing orders."""
    if close_debit <= 0:
        raise typer.BadParameter("close-debit must be positive")

    journal = Journal(journal_path)
    event = _latest_manual_trade_event(journal, symbol=symbol)
    if event is None:
        raise typer.BadParameter(f"no open manual trade found for {symbol.upper()} in {journal_path}")

    payload = event.payload
    quantity = int(payload.get("quantity", 1))
    opening_credit = float(payload["credit"])
    realized_pnl = round((opening_credit - close_debit) * 100 * quantity, 2)
    position_id = _manual_position_id(event)
    close_event = JournalEvent(
        event_type="manual_live_trade_closed",
        symbol=symbol.upper(),
        decision="closed_manually",
        reason="manual_close_fill",
        payload={
            "position_id": position_id,
            "strategy": payload.get("strategy", "Put Credit Spread"),
            "expiration": payload["expiration"],
            "short_option_symbol": payload.get("short_option_symbol", ""),
            "long_option_symbol": payload.get("long_option_symbol", ""),
            "quantity": quantity,
            "opening_credit": opening_credit,
            "close_debit": close_debit,
            "realized_pnl": realized_pnl,
            "source": "manual_close_fill",
            "bot_submission": False,
        },
    )
    journal.append(close_event)

    console.print("Manual close recorded in journal")
    console.print(f"Journal path: {journal_path}")
    console.print(f"Position id: {position_id}")
    console.print(f"Strategy: {payload.get('strategy', 'Put Credit Spread')}")
    console.print(f"Symbol: {symbol.upper()}")
    console.print(f"Opening credit: ${opening_credit:.2f}")
    console.print(f"Close debit: ${close_debit:.2f}")
    console.print(f"Realized P/L: ${realized_pnl:.2f}")
    console.print("No orders were placed; this command only records the manual close fill.")


@app.command("manage-manual-trade")
def manage_manual_trade(
    symbol: str = typer.Option("SPY", help="Underlying symbol to review."),
    current_debit: float = typer.Option(..., help="Current debit to close the spread."),
    today: str | None = typer.Option(None, help="Review date YYYY-MM-DD. Defaults to today UTC."),
    journal_path: Path = typer.Option(Path("data/journal.jsonl"), help="Audit journal JSONL path."),
) -> None:
    """Review the latest manually recorded spread against deterministic exit rules."""
    journal = Journal(journal_path)
    event = _latest_manual_trade_event(journal, symbol=symbol)
    if event is None:
        raise typer.BadParameter(f"no open manual trade found for {symbol.upper()} in {journal_path}")

    review_date = date.fromisoformat(today) if today is not None else datetime.now(timezone.utc).date()
    position = _managed_position_from_manual_event(event)
    decision = PositionManager(PositionManagerConfig()).evaluate(
        position,
        current_debit=current_debit,
        today=review_date,
    )
    journal.append(decision.to_journal_event())

    console.print("Position management review")
    console.print(f"Symbol: {position.symbol}")
    console.print(f"Position: {position.spread.short_strike:.2f}/{position.spread.long_strike:.2f} Put Credit Spread")
    console.print(f"Expiration: {position.expiration.isoformat()}")
    console.print(f"DTE: {decision.dte}")
    console.print(f"Opening credit: ${position.opening_credit:.2f}")
    console.print(f"Current debit: ${current_debit:.2f}")
    console.print(f"P/L if closed: ${decision.realized_pnl_if_closed:.2f}")
    console.print(f"Action: {decision.action}")
    console.print(f"Reason: {decision.reason}")
    console.print("No orders were placed; this command only records management guidance.")


@app.command()
def journal(limit: int = 20) -> None:
    """Show recent local audit journal events."""
    events = Journal().read_recent(limit=limit)
    if not events:
        console.print("No journal events found.")
        return
    table = Table(title="Audit Journal")
    table.add_column("Time")
    table.add_column("Type")
    table.add_column("Symbol")
    table.add_column("Decision")
    table.add_column("Reason")
    for event in events:
        table.add_row(
            event.created_at.isoformat(),
            event.event_type,
            event.symbol,
            event.decision,
            event.reason,
        )
    console.print(table)


@app.command("dashboard")
def dashboard(
    host: str = typer.Option("127.0.0.1", help="Local interface to bind."),
    port: int = typer.Option(8765, help="Local port to bind."),
    journal_path: Path = typer.Option(Path("data/journal.jsonl"), help="Audit journal JSONL path."),
) -> None:
    """Start the local read-only dashboard."""
    url = f"http://{host}:{port}"
    console.print("Starting read-only local dashboard")
    console.print(f"URL: {url}")
    console.print("No orders can be submitted from this dashboard.")
    console.print("Press Ctrl-C to stop.")
    try:
        serve_dashboard(host=host, port=port, journal_path=journal_path)
    except KeyboardInterrupt:
        console.print("Dashboard stopped.")


@app.command("report")
def report(
    today: str | None = typer.Option(None, help="Report date YYYY-MM-DD. Defaults to today UTC."),
    account_equity: float | None = typer.Option(None, help="Optional account equity to include in the report."),
    unrealized_pnl: float | None = typer.Option(None, help="Optional unrealized P/L to include in the report."),
    write_markdown: bool = typer.Option(False, help="Write markdown audit report under --reports-dir."),
    reports_dir: Path = typer.Option(Path("reports"), help="Directory for markdown reports."),
    journal_path: Path = typer.Option(Path("data/journal.jsonl"), help="Audit journal JSONL path."),
) -> None:
    """Print a daily operator report from the audit journal without placing orders."""
    report_date = date.fromisoformat(today) if today is not None else datetime.now(timezone.utc).date()
    operator_report = build_operator_report(
        Journal(journal_path),
        today=report_date,
        account_equity=account_equity,
        unrealized_pnl=unrealized_pnl,
    )
    console.print(operator_report.to_text())
    if write_markdown:
        path = write_markdown_report(operator_report, reports_dir)
        console.print(f"Markdown report written: {path}")
    console.print("No orders were placed; report is read-only.")


if __name__ == "__main__":
    app()
