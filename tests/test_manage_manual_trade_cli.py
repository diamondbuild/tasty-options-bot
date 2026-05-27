from typer.testing import CliRunner

from tasty_options_bot.cli import app
from tasty_options_bot.journal import Journal, JournalEvent


def write_manual_spy_trade(path):
    Journal(path).append(
        JournalEvent(
            event_type="manual_live_trade_entered",
            symbol="SPY",
            decision="entered_manually",
            reason="manual_tastytrade_entry",
            payload={
                "symbol": "SPY",
                "strategy": "Put Credit Spread",
                "expiration": "2026-06-26",
                "short_option_symbol": "SPY   260626P00732000",
                "long_option_symbol": "SPY   260626P00727000",
                "short_strike": 732.0,
                "long_strike": 727.0,
                "quantity": 1,
                "credit": 1.0,
            },
        )
    )


def test_manage_manual_trade_reads_latest_manual_entry_and_prints_hold_decision(tmp_path):
    journal_path = tmp_path / "journal.jsonl"
    write_manual_spy_trade(journal_path)

    result = CliRunner().invoke(
        app,
        [
            "manage-manual-trade",
            "--symbol",
            "SPY",
            "--current-debit",
            "0.75",
            "--today",
            "2026-05-26",
            "--journal-path",
            str(journal_path),
        ],
    )

    assert result.exit_code == 0
    assert "Position management review" in result.output
    assert "Action: hold" in result.output
    assert "Reason: no_exit_rule_triggered" in result.output
    assert "No orders were placed" in result.output


def test_manage_manual_trade_prints_profit_target_close_decision(tmp_path):
    journal_path = tmp_path / "journal.jsonl"
    write_manual_spy_trade(journal_path)

    result = CliRunner().invoke(
        app,
        [
            "manage-manual-trade",
            "--symbol",
            "SPY",
            "--current-debit",
            "0.50",
            "--today",
            "2026-05-26",
            "--journal-path",
            str(journal_path),
        ],
    )

    assert result.exit_code == 0
    assert "Action: close" in result.output
    assert "Reason: profit_target_hit" in result.output
    assert "P/L if closed: $50.00" in result.output


def test_record_manual_close_records_fill_and_realized_pnl(tmp_path):
    journal_path = tmp_path / "journal.jsonl"
    write_manual_spy_trade(journal_path)

    result = CliRunner().invoke(
        app,
        [
            "record-manual-close",
            "--symbol",
            "SPY",
            "--close-debit",
            "0.45",
            "--journal-path",
            str(journal_path),
        ],
    )

    assert result.exit_code == 0
    assert "Manual close recorded in journal" in result.output
    assert "Position id: manual:SPY:2026-06-26" in result.output
    assert "Opening credit: $1.00" in result.output
    assert "Close debit: $0.45" in result.output
    assert "Realized P/L: $55.00" in result.output

    events = Journal(journal_path).read_recent(limit=1)
    assert events[0].event_type == "manual_live_trade_closed"
    assert events[0].decision == "closed_manually"
    assert events[0].payload["position_id"] == "manual:SPY:2026-06-26"
    assert events[0].payload["close_debit"] == 0.45
    assert events[0].payload["realized_pnl"] == 55.0


def test_manage_manual_trade_refuses_closed_manual_position(tmp_path):
    journal_path = tmp_path / "journal.jsonl"
    write_manual_spy_trade(journal_path)
    Journal(journal_path).append(
        JournalEvent(
            event_type="manual_live_trade_closed",
            symbol="SPY",
            decision="closed_manually",
            reason="manual_close_fill",
            payload={"position_id": "manual:SPY:2026-06-26", "close_debit": 0.45},
        )
    )

    result = CliRunner().invoke(
        app,
        [
            "manage-manual-trade",
            "--symbol",
            "SPY",
            "--current-debit",
            "0.75",
            "--today",
            "2026-05-26",
            "--journal-path",
            str(journal_path),
        ],
    )

    assert result.exit_code != 0
    assert "no open manual trade found for SPY" in result.output
