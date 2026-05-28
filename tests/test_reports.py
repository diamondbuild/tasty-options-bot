from datetime import date, datetime, timezone

from typer.testing import CliRunner

from tasty_options_bot.cli import app
from tasty_options_bot.journal import Journal, JournalEvent
from tasty_options_bot.reports import build_operator_report, write_markdown_report


def test_build_operator_report_summarizes_journal_state(tmp_path):
    journal = Journal(tmp_path / "journal.jsonl")
    journal.append(
        JournalEvent(
            event_type="scanner_decision",
            symbol="SPY",
            decision="would_trade",
            reason="passed_strategy_and_risk",
            payload={"candidate": {"max_loss": 400.0}},
            created_at=datetime(2026, 5, 26, 14, 0, tzinfo=timezone.utc),
        )
    )
    journal.append(
        JournalEvent(
            event_type="scanner_decision",
            symbol="QQQ",
            decision="rejected",
            reason="credit_ratio_below_minimum",
            created_at=datetime(2026, 5, 26, 14, 1, tzinfo=timezone.utc),
        )
    )
    journal.append(
        JournalEvent(
            event_type="live_open_order_filled",
            symbol="SPY",
            decision="filled",
            payload={
                "position_id": "bot:SPY:2026-06-26:open-order-789",
                "short_option_symbol": "SPY   260626P00732000",
                "long_option_symbol": "SPY   260626P00727000",
                "opening_credit": 1.0,
                "max_loss": 400.0,
            },
            created_at=datetime(2026, 5, 26, 14, 2, tzinfo=timezone.utc),
        )
    )
    journal.append(
        JournalEvent(
            event_type="live_open_order_submitted",
            symbol="QQQ",
            decision="submitted",
            payload={"order_response": {"order": {"id": "open-order-123", "status": "Received"}}},
            created_at=datetime(2026, 5, 26, 14, 3, tzinfo=timezone.utc),
        )
    )
    journal.append(
        JournalEvent(
            event_type="manual_live_trade_closed",
            symbol="IWM",
            decision="closed_manually",
            payload={"realized_pnl": 42.5},
            created_at=datetime(2026, 5, 26, 14, 4, tzinfo=timezone.utc),
        )
    )
    journal.append(
        JournalEvent(
            event_type="kill_switch_changed",
            decision="enabled",
            payload={"kill_switch_active": True},
            created_at=datetime(2026, 5, 26, 14, 5, tzinfo=timezone.utc),
        )
    )

    report = build_operator_report(
        journal,
        today=date(2026, 5, 26),
        account_equity=3042.50,
        unrealized_pnl=-12.25,
    )

    assert report.account_equity == 3042.50
    assert report.realized_pnl_today == 42.5
    assert report.unrealized_pnl == -12.25
    assert report.open_risk == 400.0
    assert report.open_positions == 1
    assert report.candidates_found == 1
    assert report.rejected_candidates == {"credit_ratio_below_minimum": 1}
    assert report.orders_submitted == 1
    assert report.kill_switch_active is True
    assert "kill_switch_active" in report.readiness_blockers

    text = report.to_text()
    assert "Daily operator report" in text
    assert "Account equity: $3,042.50" in text
    assert "Realized P/L today: $42.50" in text
    assert "Unrealized P/L: $-12.25" in text
    assert "Open risk: $400.00" in text
    assert "Open positions: 1" in text
    assert "Candidates found: 1" in text
    assert "credit_ratio_below_minimum: 1" in text
    assert "Orders submitted: 1" in text
    assert "Kill switch active: True" in text
    assert "Readiness: BLOCKED" in text


def test_operator_report_excludes_closed_manual_trade_without_open_position_id(tmp_path):
    journal = Journal(tmp_path / "journal.jsonl")
    journal.append(
        JournalEvent(
            event_type="manual_live_trade_entered",
            symbol="SPY",
            decision="entered_manually",
            payload={
                "expiration": "2026-06-26",
                "short_option_symbol": "SPY   260626P00732000",
                "long_option_symbol": "SPY   260626P00727000",
                "short_strike": 732.0,
                "long_strike": 727.0,
                "credit": 1.0,
                "quantity": 1,
                "max_loss": 400.0,
            },
            created_at=datetime(2026, 5, 26, 14, 0, tzinfo=timezone.utc),
        )
    )
    journal.append(
        JournalEvent(
            event_type="manual_live_trade_closed",
            symbol="SPY",
            decision="closed_manually",
            payload={
                "position_id": "manual:SPY:2026-06-26",
                "realized_pnl": 17.0,
            },
            created_at=datetime(2026, 5, 28, 14, 0, tzinfo=timezone.utc),
        )
    )

    report = build_operator_report(journal, today=date(2026, 5, 28))

    assert report.open_positions == 0
    assert report.open_risk == 0.0
    assert report.realized_pnl_today == 17.0


def test_report_cli_prints_summary_and_writes_markdown(tmp_path):
    journal_path = tmp_path / "journal.jsonl"
    reports_dir = tmp_path / "reports"
    Journal(journal_path).append(
        JournalEvent(
            event_type="scanner_decision",
            symbol="SPY",
            decision="would_trade",
            reason="passed_strategy_and_risk",
            created_at=datetime(2026, 5, 26, 14, 0, tzinfo=timezone.utc),
        )
    )

    result = CliRunner().invoke(
        app,
        [
            "report",
            "--today",
            "2026-05-26",
            "--account-equity",
            "3000",
            "--unrealized-pnl",
            "12.5",
            "--write-markdown",
            "--reports-dir",
            str(reports_dir),
            "--journal-path",
            str(journal_path),
        ],
    )

    assert result.exit_code == 0
    assert "Daily operator report" in result.output
    assert "Account equity: $3,000.00" in result.output
    assert "Unrealized P/L: $12.50" in result.output
    assert "Candidates found: 1" in result.output
    path = reports_dir / "operator-report-2026-05-26.md"
    assert path.exists()
    assert "# Daily operator report" in path.read_text()


def test_write_markdown_report_creates_audit_file(tmp_path):
    journal = Journal(tmp_path / "journal.jsonl")
    journal.append(
        JournalEvent(
            event_type="scanner_decision",
            symbol="SPY",
            decision="rejected",
            reason="stale_quote",
            created_at=datetime(2026, 5, 26, 14, 0, tzinfo=timezone.utc),
        )
    )
    report = build_operator_report(journal, today=date(2026, 5, 26))

    path = write_markdown_report(report, tmp_path / "reports")

    assert path == tmp_path / "reports" / "operator-report-2026-05-26.md"
    assert path.exists()
    content = path.read_text()
    assert "# Daily operator report" in content
    assert "stale_quote: 1" in content
