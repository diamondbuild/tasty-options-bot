import json

from typer.testing import CliRunner

from tasty_options_bot.cli import _build_manual_trade_event, app


def test_build_manual_trade_event_calculates_defined_risk_fields():
    event = _build_manual_trade_event(
        symbol="SPY",
        strategy="Put Credit Spread",
        expiration="2026-06-26",
        short_option_symbol="SPY   260626P00732000",
        long_option_symbol="SPY   260626P00727000",
        short_strike=732,
        long_strike=727,
        quantity=1,
        credit=1.00,
        starting_equity=3000,
    )

    assert event.event_type == "manual_live_trade_entered"
    assert event.symbol == "SPY"
    assert event.decision == "entered_manually"
    assert event.reason == "manual_tastytrade_entry"
    assert event.payload["bot_submission"] is False
    assert event.payload["max_profit"] == 100.0
    assert event.payload["max_loss"] == 400.0
    assert event.payload["breakeven"] == 731.0
    assert event.payload["account_risk_percent"] == 13.33
    assert event.payload["profit_target_debit"] == 0.5
    assert event.payload["loss_exit_debit"] == 2.0


def test_record_manual_trade_writes_audit_journal_without_submission(tmp_path):
    journal_path = tmp_path / "journal.jsonl"

    result = CliRunner().invoke(
        app,
        [
            "record-manual-trade",
            "--symbol",
            "SPY",
            "--strategy",
            "Put Credit Spread",
            "--expiration",
            "2026-06-26",
            "--short-option-symbol",
            "SPY   260626P00732000",
            "--long-option-symbol",
            "SPY   260626P00727000",
            "--short-strike",
            "732",
            "--long-strike",
            "727",
            "--quantity",
            "1",
            "--credit",
            "1.00",
            "--starting-equity",
            "3000",
            "--journal-path",
            str(journal_path),
        ],
    )

    assert result.exit_code == 0
    assert "Manual trade recorded in journal" in result.output
    assert "Bot submission: False" in result.output
    assert "No orders were placed" in result.output

    records = [json.loads(line) for line in journal_path.read_text().splitlines()]
    assert len(records) == 1
    record = records[0]
    assert record["event_type"] == "manual_live_trade_entered"
    assert record["decision"] == "entered_manually"
    assert record["payload"]["short_option_symbol"] == "SPY   260626P00732000"
    assert record["payload"]["long_option_symbol"] == "SPY   260626P00727000"
    assert record["payload"]["credit"] == 1.0
    assert record["payload"]["submission_allowed"] is False
