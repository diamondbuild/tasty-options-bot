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
                "max_loss": 400.0,
            },
        )
    )


def test_manage_live_positions_matches_journaled_spread_and_uses_live_quotes(monkeypatch, tmp_path):
    journal_path = tmp_path / "journal.jsonl"
    write_manual_spy_trade(journal_path)
    calls = {}

    class FakeClient:
        def get_positions(self):
            return [
                {"symbol": "SPY   260626P00732000", "quantity": "-1", "instrument-type": "Equity Option"},
                {"symbol": "SPY   260626P00727000", "quantity": "1", "instrument-type": "Equity Option"},
            ]

        def get_equity_option_market_data(self, symbols):
            calls["symbols"] = symbols
            return [
                {"symbol": "SPY   260626P00732000", "bid": "0.70", "ask": "0.76"},
                {"symbol": "SPY   260626P00727000", "bid": "0.20", "ask": "0.24"},
            ]

    monkeypatch.setattr("tasty_options_bot.cli.build_tastytrade_client", lambda: FakeClient())
    monkeypatch.setattr("tasty_options_bot.cli.authenticate_client", lambda client: None)

    result = CliRunner().invoke(
        app,
        [
            "manage-live-positions",
            "--symbol",
            "SPY",
            "--today",
            "2026-05-26",
            "--journal-path",
            str(journal_path),
        ],
    )

    assert result.exit_code == 0
    assert calls["symbols"] == ["SPY   260626P00732000", "SPY   260626P00727000"]
    assert "Live position reconciliation" in result.output
    assert "Matched journaled spread: True" in result.output
    assert "Estimated debit to close: $0.56" in result.output
    assert "P/L if closed: $44.00" in result.output
    assert "Action: hold" in result.output
    assert "New entries blocked: True" in result.output
    assert "No orders were placed" in result.output


def test_manage_live_positions_flags_unexpected_live_positions(monkeypatch, tmp_path):
    journal_path = tmp_path / "journal.jsonl"
    write_manual_spy_trade(journal_path)

    class FakeClient:
        def get_positions(self):
            return [
                {"symbol": "QQQ   260626P00500000", "quantity": "-1", "instrument-type": "Equity Option"},
            ]

        def get_equity_option_market_data(self, symbols):
            raise AssertionError("market data should not be fetched for unmatched positions")

    monkeypatch.setattr("tasty_options_bot.cli.build_tastytrade_client", lambda: FakeClient())
    monkeypatch.setattr("tasty_options_bot.cli.authenticate_client", lambda client: None)

    result = CliRunner().invoke(
        app,
        [
            "manage-live-positions",
            "--symbol",
            "SPY",
            "--today",
            "2026-05-26",
            "--journal-path",
            str(journal_path),
        ],
    )

    assert result.exit_code == 0
    assert "Matched journaled spread: False" in result.output
    assert "Unexpected live positions: True" in result.output
    assert "New entries blocked: True" in result.output
    assert "No orders were placed" in result.output


def test_manage_live_positions_prints_close_preview_when_action_is_close(monkeypatch, tmp_path):
    journal_path = tmp_path / "journal.jsonl"
    write_manual_spy_trade(journal_path)

    class FakeClient:
        def get_positions(self):
            return [
                {"symbol": "SPY   260626P00732000", "quantity": "-1", "instrument-type": "Equity Option"},
                {"symbol": "SPY   260626P00727000", "quantity": "1", "instrument-type": "Equity Option"},
            ]

        def get_equity_option_market_data(self, symbols):
            return [
                {"symbol": "SPY   260626P00732000", "bid": "0.60", "ask": "0.65"},
                {"symbol": "SPY   260626P00727000", "bid": "0.15", "ask": "0.18"},
            ]

    monkeypatch.setattr("tasty_options_bot.cli.build_tastytrade_client", lambda: FakeClient())
    monkeypatch.setattr("tasty_options_bot.cli.authenticate_client", lambda client: None)

    result = CliRunner().invoke(
        app,
        [
            "manage-live-positions",
            "--symbol",
            "SPY",
            "--today",
            "2026-06-06",
            "--close-preview",
            "--journal-path",
            str(journal_path),
        ],
    )

    assert result.exit_code == 0
    assert "Action: close" in result.output
    assert "Closing Order Ticket Preview — Dry Run Only" in result.output
    assert "Net Price Effect" in result.output
    assert "debit" in result.output
    assert "Estimated Debit" in result.output
    assert "0.50" in result.output
    assert "buy_to_close 1 SPY   260626P00732000" in result.output
    assert "sell_to_close 1 SPY   260626P00727000" in result.output
    assert "Submission Allowed" in result.output
    assert "False" in result.output
    assert "No orders were placed" in result.output


def test_manage_live_positions_does_not_print_close_preview_on_hold_without_force(monkeypatch, tmp_path):
    journal_path = tmp_path / "journal.jsonl"
    write_manual_spy_trade(journal_path)

    class FakeClient:
        def get_positions(self):
            return [
                {"symbol": "SPY   260626P00732000", "quantity": "-1", "instrument-type": "Equity Option"},
                {"symbol": "SPY   260626P00727000", "quantity": "1", "instrument-type": "Equity Option"},
            ]

        def get_equity_option_market_data(self, symbols):
            return [
                {"symbol": "SPY   260626P00732000", "bid": "0.70", "ask": "0.76"},
                {"symbol": "SPY   260626P00727000", "bid": "0.20", "ask": "0.24"},
            ]

    monkeypatch.setattr("tasty_options_bot.cli.build_tastytrade_client", lambda: FakeClient())
    monkeypatch.setattr("tasty_options_bot.cli.authenticate_client", lambda client: None)

    result = CliRunner().invoke(
        app,
        [
            "manage-live-positions",
            "--symbol",
            "SPY",
            "--today",
            "2026-05-26",
            "--close-preview",
            "--journal-path",
            str(journal_path),
        ],
    )

    assert result.exit_code == 0
    assert "Action: hold" in result.output
    assert "No close preview because action is hold" in result.output
    assert "Closing Order Ticket Preview" not in result.output


def test_manage_live_positions_force_close_preview_allows_review_on_hold(monkeypatch, tmp_path):
    journal_path = tmp_path / "journal.jsonl"
    write_manual_spy_trade(journal_path)

    class FakeClient:
        def get_positions(self):
            return [
                {"symbol": "SPY   260626P00732000", "quantity": "-1", "instrument-type": "Equity Option"},
                {"symbol": "SPY   260626P00727000", "quantity": "1", "instrument-type": "Equity Option"},
            ]

        def get_equity_option_market_data(self, symbols):
            return [
                {"symbol": "SPY   260626P00732000", "bid": "0.70", "ask": "0.76"},
                {"symbol": "SPY   260626P00727000", "bid": "0.20", "ask": "0.24"},
            ]

    monkeypatch.setattr("tasty_options_bot.cli.build_tastytrade_client", lambda: FakeClient())
    monkeypatch.setattr("tasty_options_bot.cli.authenticate_client", lambda client: None)

    result = CliRunner().invoke(
        app,
        [
            "manage-live-positions",
            "--symbol",
            "SPY",
            "--today",
            "2026-05-26",
            "--close-preview",
            "--force-close-preview",
            "--journal-path",
            str(journal_path),
        ],
    )

    assert result.exit_code == 0
    assert "Action: hold" in result.output
    assert "Closing Order Ticket Preview — Dry Run Only" in result.output
    assert "Estimated Debit" in result.output
    assert "0.56" in result.output


def test_manage_live_positions_submit_close_refuses_when_action_is_hold(monkeypatch, tmp_path):
    journal_path = tmp_path / "journal.jsonl"
    write_manual_spy_trade(journal_path)

    class FakeClient:
        def get_positions(self):
            return [
                {"symbol": "SPY   260626P00732000", "quantity": "-1", "instrument-type": "Equity Option"},
                {"symbol": "SPY   260626P00727000", "quantity": "1", "instrument-type": "Equity Option"},
            ]

        def get_equity_option_market_data(self, symbols):
            return [
                {"symbol": "SPY   260626P00732000", "bid": "0.70", "ask": "0.76"},
                {"symbol": "SPY   260626P00727000", "bid": "0.20", "ask": "0.24"},
            ]

        def submit_order_payload(self, payload, *, approved):
            raise AssertionError("hold decisions must not submit close orders")

    monkeypatch.setattr("tasty_options_bot.cli.build_tastytrade_client", lambda: FakeClient())
    monkeypatch.setattr("tasty_options_bot.cli.authenticate_client", lambda client: None)

    result = CliRunner().invoke(
        app,
        [
            "manage-live-positions",
            "--symbol",
            "SPY",
            "--today",
            "2026-05-26",
            "--submit-close",
            "--i-understand-live-order",
            "--confirm-symbol",
            "SPY",
            "--journal-path",
            str(journal_path),
        ],
    )

    assert result.exit_code != 0
    assert "submit-close requires action close" in result.output


def test_manage_live_positions_submit_close_posts_payload_only_with_all_confirmations(monkeypatch, tmp_path):
    journal_path = tmp_path / "journal.jsonl"
    write_manual_spy_trade(journal_path)
    submissions = []

    class FakeClient:
        def get_positions(self):
            return [
                {"symbol": "SPY   260626P00732000", "quantity": "-1", "instrument-type": "Equity Option"},
                {"symbol": "SPY   260626P00727000", "quantity": "1", "instrument-type": "Equity Option"},
            ]

        def get_equity_option_market_data(self, symbols):
            return [
                {"symbol": "SPY   260626P00732000", "bid": "0.60", "ask": "0.65"},
                {"symbol": "SPY   260626P00727000", "bid": "0.15", "ask": "0.18"},
            ]

        def submit_order_payload(self, payload, *, approved):
            submissions.append({"payload": payload, "approved": approved})
            return {"order": {"id": "order-123", "status": "Received"}}

    monkeypatch.setattr("tasty_options_bot.cli.build_tastytrade_client", lambda: FakeClient())
    monkeypatch.setattr("tasty_options_bot.cli.authenticate_client", lambda client: None)

    result = CliRunner().invoke(
        app,
        [
            "manage-live-positions",
            "--symbol",
            "SPY",
            "--today",
            "2026-06-06",
            "--submit-close",
            "--i-understand-live-order",
            "--confirm-symbol",
            "SPY",
            "--journal-path",
            str(journal_path),
        ],
    )

    assert result.exit_code == 0
    assert "Action: close" in result.output
    assert "LIVE CLOSE ORDER SUBMITTED" in result.output
    assert "Order id: order-123" in result.output
    assert submissions == [
        {
            "approved": True,
            "payload": {
                "order-type": "Limit",
                "time-in-force": "Day",
                "price-effect": "Debit",
                "price": "0.50",
                "source": "tasty-options-bot-close-preview",
                "legs": [
                    {
                        "action": "Buy to Close",
                        "instrument-type": "Equity Option",
                        "symbol": "SPY   260626P00732000",
                        "quantity": 1,
                    },
                    {
                        "action": "Sell to Close",
                        "instrument-type": "Equity Option",
                        "symbol": "SPY   260626P00727000",
                        "quantity": 1,
                    },
                ],
            },
        }
    ]


def test_manage_live_positions_submit_close_refuses_above_max_close_debit(monkeypatch, tmp_path):
    journal_path = tmp_path / "journal.jsonl"
    write_manual_spy_trade(journal_path)

    class FakeClient:
        def get_positions(self):
            return [
                {"symbol": "SPY   260626P00732000", "quantity": "-1", "instrument-type": "Equity Option"},
                {"symbol": "SPY   260626P00727000", "quantity": "1", "instrument-type": "Equity Option"},
            ]

        def get_equity_option_market_data(self, symbols):
            return [
                {"symbol": "SPY   260626P00732000", "bid": "0.60", "ask": "0.65"},
                {"symbol": "SPY   260626P00727000", "bid": "0.15", "ask": "0.18"},
            ]

        def submit_order_payload(self, payload, *, approved):
            raise AssertionError("close debit above cap must not submit")

    monkeypatch.setattr("tasty_options_bot.cli.build_tastytrade_client", lambda: FakeClient())
    monkeypatch.setattr("tasty_options_bot.cli.authenticate_client", lambda client: None)

    result = CliRunner().invoke(
        app,
        [
            "manage-live-positions",
            "--symbol",
            "SPY",
            "--today",
            "2026-06-06",
            "--submit-close",
            "--i-understand-live-order",
            "--confirm-symbol",
            "SPY",
            "--max-close-debit",
            "0.45",
            "--journal-path",
            str(journal_path),
        ],
    )

    assert result.exit_code != 0
    assert "estimated close debit 0.50 exceeds max close debit 0.45" in result.output


def test_manage_live_positions_submit_close_refuses_wide_leg_market(monkeypatch, tmp_path):
    journal_path = tmp_path / "journal.jsonl"
    write_manual_spy_trade(journal_path)

    class FakeClient:
        def get_positions(self):
            return [
                {"symbol": "SPY   260626P00732000", "quantity": "-1", "instrument-type": "Equity Option"},
                {"symbol": "SPY   260626P00727000", "quantity": "1", "instrument-type": "Equity Option"},
            ]

        def get_equity_option_market_data(self, symbols):
            return [
                {"symbol": "SPY   260626P00732000", "bid": "0.20", "ask": "0.65"},
                {"symbol": "SPY   260626P00727000", "bid": "0.15", "ask": "0.18"},
            ]

        def submit_order_payload(self, payload, *, approved):
            raise AssertionError("wide leg markets must not submit")

    monkeypatch.setattr("tasty_options_bot.cli.build_tastytrade_client", lambda: FakeClient())
    monkeypatch.setattr("tasty_options_bot.cli.authenticate_client", lambda client: None)

    result = CliRunner().invoke(
        app,
        [
            "manage-live-positions",
            "--symbol",
            "SPY",
            "--today",
            "2026-06-06",
            "--submit-close",
            "--i-understand-live-order",
            "--confirm-symbol",
            "SPY",
            "--max-close-leg-bid-ask-width",
            "0.20",
            "--journal-path",
            str(journal_path),
        ],
    )

    assert result.exit_code != 0
    assert "short leg bid/ask width 0.45 exceeds max close leg bid/ask" in result.output
    assert "width 0.20" in result.output


def test_manage_live_positions_submit_close_refuses_duplicate_submitted_close(monkeypatch, tmp_path):
    journal_path = tmp_path / "journal.jsonl"
    write_manual_spy_trade(journal_path)
    Journal(journal_path).append(
        JournalEvent(
            event_type="live_close_order_submitted",
            symbol="SPY",
            decision="submitted",
            reason="dte_exit_threshold",
            payload={
                "position_id": "manual:SPY:2026-06-26",
                "order_response": {"order": {"id": "order-123", "status": "Received"}},
            },
        )
    )

    class FakeClient:
        def get_positions(self):
            return [
                {"symbol": "SPY   260626P00732000", "quantity": "-1", "instrument-type": "Equity Option"},
                {"symbol": "SPY   260626P00727000", "quantity": "1", "instrument-type": "Equity Option"},
            ]

        def get_equity_option_market_data(self, symbols):
            return [
                {"symbol": "SPY   260626P00732000", "bid": "0.60", "ask": "0.65"},
                {"symbol": "SPY   260626P00727000", "bid": "0.15", "ask": "0.18"},
            ]

        def submit_order_payload(self, payload, *, approved):
            raise AssertionError("duplicate close submissions must not submit")

    monkeypatch.setattr("tasty_options_bot.cli.build_tastytrade_client", lambda: FakeClient())
    monkeypatch.setattr("tasty_options_bot.cli.authenticate_client", lambda client: None)

    result = CliRunner().invoke(
        app,
        [
            "manage-live-positions",
            "--symbol",
            "SPY",
            "--today",
            "2026-06-06",
            "--submit-close",
            "--i-understand-live-order",
            "--confirm-symbol",
            "SPY",
            "--journal-path",
            str(journal_path),
        ],
    )

    assert result.exit_code != 0
    assert "close order already submitted for position" in result.output
    assert "manual:SPY:2026-06-26" in result.output


def test_manage_live_positions_submit_close_refuses_when_kill_switch_enabled(monkeypatch, tmp_path):
    journal_path = tmp_path / "journal.jsonl"
    write_manual_spy_trade(journal_path)
    Journal(journal_path).append(
        JournalEvent(
            event_type="kill_switch_changed",
            symbol="",
            decision="enabled",
            reason="operator_requested",
            payload={"kill_switch_active": True},
        )
    )

    class FakeClient:
        def get_positions(self):
            return [
                {"symbol": "SPY   260626P00732000", "quantity": "-1", "instrument-type": "Equity Option"},
                {"symbol": "SPY   260626P00727000", "quantity": "1", "instrument-type": "Equity Option"},
            ]

        def get_equity_option_market_data(self, symbols):
            return [
                {"symbol": "SPY   260626P00732000", "bid": "0.60", "ask": "0.65"},
                {"symbol": "SPY   260626P00727000", "bid": "0.15", "ask": "0.18"},
            ]

        def submit_order_payload(self, payload, *, approved):
            raise AssertionError("kill switch must block close submissions")

    monkeypatch.setattr("tasty_options_bot.cli.build_tastytrade_client", lambda: FakeClient())
    monkeypatch.setattr("tasty_options_bot.cli.authenticate_client", lambda client: None)

    result = CliRunner().invoke(
        app,
        [
            "manage-live-positions",
            "--symbol",
            "SPY",
            "--today",
            "2026-06-06",
            "--submit-close",
            "--i-understand-live-order",
            "--confirm-symbol",
            "SPY",
            "--journal-path",
            str(journal_path),
        ],
    )

    assert result.exit_code != 0
    assert "kill_switch_active" in result.output


def test_reconcile_submitted_orders_records_working_close_order_status(monkeypatch, tmp_path):
    journal_path = tmp_path / "journal.jsonl"
    write_manual_spy_trade(journal_path)
    Journal(journal_path).append(
        JournalEvent(
            event_type="live_close_order_submitted",
            symbol="SPY",
            decision="submitted",
            reason="dte_exit_threshold",
            payload={
                "position_id": "manual:SPY:2026-06-26",
                "order_response": {"order": {"id": "order-123", "status": "Received"}},
            },
        )
    )
    fetched = []

    class FakeClient:
        def get_order(self, order_id):
            fetched.append(order_id)
            return {"order": {"id": order_id, "status": "Live", "filled-quantity": "0"}}

    monkeypatch.setattr("tasty_options_bot.cli.build_tastytrade_client", lambda: FakeClient())
    monkeypatch.setattr("tasty_options_bot.cli.authenticate_client", lambda client: None)

    result = CliRunner().invoke(
        app,
        [
            "reconcile-submitted-orders",
            "--journal-path",
            str(journal_path),
        ],
    )

    assert result.exit_code == 0
    assert fetched == ["order-123"]
    assert "Submitted order reconciliation" in result.output
    assert "order-123" in result.output
    assert "Live" in result.output
    events = Journal(journal_path).read_recent(limit=5)
    reconciliation = next(event for event in events if event.event_type == "live_close_order_reconciled")
    assert reconciliation.decision == "working"
    assert reconciliation.payload["order_id"] == "order-123"
    assert reconciliation.payload["status"] == "Live"
    assert reconciliation.payload["position_id"] == "manual:SPY:2026-06-26"


def test_reconcile_submitted_orders_records_filled_close_and_realized_pnl(monkeypatch, tmp_path):
    journal_path = tmp_path / "journal.jsonl"
    write_manual_spy_trade(journal_path)
    Journal(journal_path).append(
        JournalEvent(
            event_type="live_close_order_submitted",
            symbol="SPY",
            decision="submitted",
            reason="dte_exit_threshold",
            payload={
                "position_id": "manual:SPY:2026-06-26",
                "order_response": {"order": {"id": "order-456", "status": "Received"}},
            },
        )
    )

    class FakeClient:
        def get_order(self, order_id):
            return {
                "order": {
                    "id": order_id,
                    "status": "Filled",
                    "filled-quantity": "1",
                    "average-fill-price": "0.45",
                }
            }

    monkeypatch.setattr("tasty_options_bot.cli.build_tastytrade_client", lambda: FakeClient())
    monkeypatch.setattr("tasty_options_bot.cli.authenticate_client", lambda client: None)

    result = CliRunner().invoke(
        app,
        [
            "reconcile-submitted-orders",
            "--journal-path",
            str(journal_path),
        ],
    )

    assert result.exit_code == 0
    assert "Filled" in result.output
    assert "Realized P/L: $55.00" in result.output
    events = Journal(journal_path).read_recent(limit=10)
    filled = next(event for event in events if event.event_type == "live_close_order_filled")
    assert filled.decision == "filled"
    assert filled.payload["order_id"] == "order-456"
    assert filled.payload["close_debit"] == 0.45
    assert filled.payload["realized_pnl"] == 55.0
    assert filled.payload["bot_submission"] is True


def test_reconcile_submitted_orders_skips_already_terminal_orders(monkeypatch, tmp_path):
    journal_path = tmp_path / "journal.jsonl"
    write_manual_spy_trade(journal_path)
    Journal(journal_path).append(
        JournalEvent(
            event_type="live_close_order_submitted",
            symbol="SPY",
            decision="submitted",
            reason="dte_exit_threshold",
            payload={
                "position_id": "manual:SPY:2026-06-26",
                "order_response": {"order": {"id": "order-456", "status": "Received"}},
            },
        )
    )
    Journal(journal_path).append(
        JournalEvent(
            event_type="live_close_order_filled",
            symbol="SPY",
            decision="filled",
            reason="order_status_filled",
            payload={"position_id": "manual:SPY:2026-06-26", "order_id": "order-456"},
        )
    )

    class FakeClient:
        def get_order(self, order_id):
            raise AssertionError("terminal orders should not be fetched again")

    monkeypatch.setattr("tasty_options_bot.cli.build_tastytrade_client", lambda: FakeClient())
    monkeypatch.setattr("tasty_options_bot.cli.authenticate_client", lambda client: None)

    result = CliRunner().invoke(
        app,
        [
            "reconcile-submitted-orders",
            "--journal-path",
            str(journal_path),
        ],
    )

    assert result.exit_code == 0
    assert "No submitted orders need reconciliation" in result.output


def write_bot_open_fill(path):
    Journal(path).append(
        JournalEvent(
            event_type="live_open_order_filled",
            symbol="SPY",
            decision="filled",
            reason="order_status_filled",
            payload={
                "position_id": "bot:SPY:2026-06-26:open-order-789",
                "order_id": "open-order-789",
                "strategy": "Put Credit Spread",
                "expiration": "2026-06-26",
                "short_option_symbol": "SPY   260626P00732000",
                "long_option_symbol": "SPY   260626P00727000",
                "short_strike": 732.0,
                "long_strike": 727.0,
                "quantity": 1,
                "opening_credit": 1.0,
                "credit": 1.0,
                "bot_submission": True,
            },
        )
    )


def test_reconcile_submitted_orders_records_filled_open_as_managed_position(monkeypatch, tmp_path):
    journal_path = tmp_path / "journal.jsonl"
    Journal(journal_path).append(
        JournalEvent(
            event_type="live_open_order_submitted",
            symbol="SPY",
            decision="submitted",
            reason="passed_strategy_and_risk",
            payload={
                "candidate": {
                    "strategy": "Put Credit Spread",
                    "symbol": "SPY",
                    "expiration": "2026-06-26",
                    "dte": 31,
                    "short_strike": 732.0,
                    "long_strike": 727.0,
                    "short_option_symbol": "SPY   260626P00732000",
                    "long_option_symbol": "SPY   260626P00727000",
                    "short_delta": -0.24,
                    "credit": 1.0,
                    "max_loss": 400.0,
                    "credit_ratio": 0.20,
                },
                "order_response": {"order": {"id": "open-order-789", "status": "Received"}},
            },
        )
    )

    class FakeClient:
        def get_order(self, order_id):
            return {
                "order": {
                    "id": order_id,
                    "status": "Filled",
                    "filled-quantity": "1",
                    "average-fill-price": "1.02",
                }
            }

    monkeypatch.setattr("tasty_options_bot.cli.build_tastytrade_client", lambda: FakeClient())
    monkeypatch.setattr("tasty_options_bot.cli.authenticate_client", lambda client: None)

    result = CliRunner().invoke(
        app,
        ["reconcile-submitted-orders", "--journal-path", str(journal_path)],
    )

    assert result.exit_code == 0
    assert "open-order-789" in result.output
    assert "Filled" in result.output
    assert "Opening fill recorded" in result.output
    events = Journal(journal_path).read_recent(limit=10)
    reconciled = next(event for event in events if event.event_type == "live_open_order_reconciled")
    assert reconciled.decision == "filled"
    assert reconciled.payload["order_id"] == "open-order-789"
    filled = next(event for event in events if event.event_type == "live_open_order_filled")
    assert filled.decision == "filled"
    assert filled.payload["position_id"] == "bot:SPY:2026-06-26:open-order-789"
    assert filled.payload["opening_credit"] == 1.02
    assert filled.payload["short_option_symbol"] == "SPY   260626P00732000"
    assert filled.payload["long_option_symbol"] == "SPY   260626P00727000"
    assert filled.payload["bot_submission"] is True


def test_manage_live_positions_can_manage_bot_filled_open_position(monkeypatch, tmp_path):
    journal_path = tmp_path / "journal.jsonl"
    write_bot_open_fill(journal_path)

    class FakeClient:
        def get_positions(self):
            return [
                {"symbol": "SPY   260626P00732000", "quantity": "-1", "instrument-type": "Equity Option"},
                {"symbol": "SPY   260626P00727000", "quantity": "1", "instrument-type": "Equity Option"},
            ]

        def get_equity_option_market_data(self, symbols):
            return [
                {"symbol": "SPY   260626P00732000", "bid": "0.70", "ask": "0.76"},
                {"symbol": "SPY   260626P00727000", "bid": "0.20", "ask": "0.24"},
            ]

    monkeypatch.setattr("tasty_options_bot.cli.build_tastytrade_client", lambda: FakeClient())
    monkeypatch.setattr("tasty_options_bot.cli.authenticate_client", lambda client: None)

    result = CliRunner().invoke(
        app,
        [
            "manage-live-positions",
            "--symbol",
            "SPY",
            "--today",
            "2026-05-26",
            "--journal-path",
            str(journal_path),
        ],
    )

    assert result.exit_code == 0
    assert "Matched journaled spread: True" in result.output
    assert "Estimated debit to close: $0.56" in result.output
    assert "P/L if closed: $44.00" in result.output


def test_reconcile_submitted_orders_skips_already_filled_open_order(monkeypatch, tmp_path):
    journal_path = tmp_path / "journal.jsonl"
    Journal(journal_path).append(
        JournalEvent(
            event_type="live_open_order_submitted",
            symbol="SPY",
            decision="submitted",
            payload={
                "candidate": {"expiration": "2026-06-26"},
                "order_response": {"order": {"id": "open-order-789", "status": "Received"}},
            },
        )
    )
    write_bot_open_fill(journal_path)

    class FakeClient:
        def get_order(self, order_id):
            raise AssertionError("filled open orders should not be fetched again")

    monkeypatch.setattr("tasty_options_bot.cli.build_tastytrade_client", lambda: FakeClient())
    monkeypatch.setattr("tasty_options_bot.cli.authenticate_client", lambda client: None)

    result = CliRunner().invoke(
        app,
        ["reconcile-submitted-orders", "--journal-path", str(journal_path)],
    )

    assert result.exit_code == 0
    assert "No submitted orders need reconciliation" in result.output
