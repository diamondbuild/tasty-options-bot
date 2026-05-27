from datetime import date, datetime, timezone

from typer.testing import CliRunner

from tasty_options_bot.cli import app
from tasty_options_bot.config import BotConfig
from tasty_options_bot.dashboard import build_dashboard_snapshot, render_dashboard_html
from tasty_options_bot.journal import Journal, JournalEvent


def test_build_dashboard_snapshot_is_read_only_and_summarizes_operator_state(tmp_path):
    journal = Journal(tmp_path / "journal.jsonl")
    journal.append(
        JournalEvent(
            event_type="manual_live_trade_entered",
            symbol="SPY",
            decision="entered_manually",
            reason="manual_tastytrade_entry",
            payload={
                "position_id": "manual:SPY:2026-06-26",
                "strategy_type": "Put Credit Spread",
                "short_option_symbol": "SPY   260626P00595000",
                "long_option_symbol": "SPY   260626P00590000",
                "opening_credit": 1.0,
                "max_loss": 400.0,
            },
            created_at=datetime(2026, 5, 26, 14, 0, tzinfo=timezone.utc),
        )
    )
    journal.append(
        JournalEvent(
            event_type="exit_decision",
            symbol="SPY",
            decision="hold",
            reason="no_exit_rule_triggered",
            payload={"estimated_debit_to_close": 1.03, "pnl_if_closed": -3.0, "dte": 30},
            created_at=datetime(2026, 5, 27, 14, 9, tzinfo=timezone.utc),
        )
    )

    before = journal.path.read_text(encoding="utf-8")
    snapshot = build_dashboard_snapshot(
        config=BotConfig(),
        journal=journal,
        today=date(2026, 5, 27),
    )
    after = journal.path.read_text(encoding="utf-8")

    assert after == before
    assert snapshot.safety.live_trading is False
    assert snapshot.safety.manual_approval_required is True
    assert snapshot.safety.market_orders_allowed is False
    assert snapshot.report.open_positions == 1
    assert snapshot.report.open_risk == 400.0
    assert snapshot.report.readiness == "BLOCKED"
    assert snapshot.open_positions[0].position_id == "manual:SPY:2026-06-26"
    assert snapshot.open_positions[0].strategy_type == "Put Credit Spread"
    assert snapshot.latest_exit_decision is not None
    assert snapshot.latest_exit_decision.decision == "hold"
    assert snapshot.latest_exit_decision.estimated_debit_to_close == 1.03


def test_render_dashboard_html_contains_safe_local_dashboard_sections(tmp_path):
    journal = Journal(tmp_path / "journal.jsonl")
    journal.append(
        JournalEvent(
            event_type="manual_live_trade_entered",
            symbol="SPY",
            decision="entered_manually",
            payload={"position_id": "manual:SPY:2026-06-26", "max_loss": 400.0},
            created_at=datetime(2026, 5, 26, 14, 0, tzinfo=timezone.utc),
        )
    )
    snapshot = build_dashboard_snapshot(config=BotConfig(), journal=journal, today=date(2026, 5, 27))

    html = render_dashboard_html(snapshot)

    assert "Tasty Options Bot Dashboard" in html
    assert "Mode: Read-only Local Dashboard" in html
    assert "Live Trading Disabled" in html
    assert "Manual Approval Required" in html
    assert "Market Orders Disabled" in html
    assert "Open Positions" in html
    assert "Journal &amp; History" in html
    assert "manual:SPY:2026-06-26" in html
    assert "No orders can be submitted from this dashboard" in html
    assert "submit-open" not in html
    assert "submit-close" not in html


def test_render_dashboard_html_contains_refresh_candidate_account_quote_and_ticket_sections(tmp_path):
    journal = Journal(tmp_path / "journal.jsonl")
    journal.append(
        JournalEvent(
            event_type="account_balance_snapshot",
            symbol="",
            decision="read_only",
            reason="balance_check",
            payload={
                "net_liquidating_value": 3042.50,
                "cash_balance": 2900.25,
                "option_buying_power": 1800.00,
            },
            created_at=datetime(2026, 5, 27, 13, 55, tzinfo=timezone.utc),
        )
    )
    journal.append(
        JournalEvent(
            event_type="scanner_decision",
            symbol="SPY",
            decision="would_trade",
            reason="passed_strategy_and_risk",
            payload={
                "strategy_type": "Put Credit Spread",
                "expiration": "2026-06-26",
                "dte": 30,
                "short_strike": 595.0,
                "long_strike": 590.0,
                "short_option_symbol": "SPY   260626P00595000",
                "long_option_symbol": "SPY   260626P00590000",
                "short_delta": -0.2,
                "credit": 1.0,
                "max_loss": 400.0,
                "credit_ratio": 0.2,
                "quote_time": "2026-05-27T13:59:30+00:00",
            },
            created_at=datetime(2026, 5, 27, 14, 0, tzinfo=timezone.utc),
        )
    )
    snapshot = build_dashboard_snapshot(config=BotConfig(), journal=journal, today=date(2026, 5, 27))

    html = render_dashboard_html(snapshot)

    assert "refresh" in html.lower()
    assert "Scanner Candidates" in html
    assert "Current Account / Balance" in html
    assert "$3,042.50" in html
    assert "Live Quote Timestamps" in html
    assert "2026-05-27T13:59:30+00:00" in html
    assert "Preview-Only Order Ticket" in html
    assert "preview_only_not_submitted" in html
    assert "sell_to_open" in html
    assert "buy_to_open" in html
    assert "SPY   260626P00595000" in html
    assert "submit-open" not in html



def test_dashboard_cli_exposes_safe_local_server_command():
    result = CliRunner().invoke(app, ["dashboard", "--help"])

    assert result.exit_code == 0
    assert "Start the local read-only dashboard" in result.output
    assert "--host" in result.output
    assert "--port" in result.output
