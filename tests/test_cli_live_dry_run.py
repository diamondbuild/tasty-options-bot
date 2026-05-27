from datetime import date, datetime, timezone

from typer.testing import CliRunner

from tasty_options_bot.cli import (
    _apply_live_dry_run_preset,
    _build_order_ticket_preview,
    _build_risk_manager,
    _build_scanner_config,
    _effective_kill_switch_active,
    _is_us_market_hours,
    _build_strategy,
    _format_decision_row,
    _rank_decisions,
    app,
)
from tasty_options_bot.config import BotConfig
from tasty_options_bot.journal import Journal, JournalEvent
from tasty_options_bot.scanner import ScannerDecision
from tasty_options_bot.strategy import SpreadCandidate


def test_live_dry_run_accepts_symbol_as_positional_argument(monkeypatch):
    calls = {}

    class FakeClient:
        session_token = "token"

        def get_nested_option_chain(self, symbol):
            calls["symbol"] = symbol
            return []

    monkeypatch.setattr("tasty_options_bot.cli.build_tastytrade_client", lambda: FakeClient())
    monkeypatch.setattr("tasty_options_bot.cli.authenticate_client", lambda client: None)

    result = CliRunner().invoke(app, ["live-dry-run", "SPY"])

    assert result.exit_code == 0
    assert calls["symbol"] == "SPY"
    assert "No option contracts returned for filters." in result.output


def test_scheduler_runs_one_dry_run_cycle_without_live_submission(monkeypatch, tmp_path):
    calls = []

    def fake_live_dry_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr("tasty_options_bot.cli._is_us_market_hours", lambda: True)
    monkeypatch.setattr("tasty_options_bot.cli.live_dry_run", fake_live_dry_run)

    result = CliRunner().invoke(
        app,
        ["scheduler", "--symbol", "SPY", "--cycles", "1", "--journal-path", str(tmp_path / "journal.jsonl")],
    )

    assert result.exit_code == 0
    assert "Scheduler mode: dry-run" in result.output
    assert "Scheduler safety: submit_open=False" in result.output
    assert "Scheduler cycle 1/1" in result.output
    assert len(calls) == 1
    assert calls[0]["symbol"] == "SPY"
    assert calls[0]["submit_open"] is False
    assert calls[0]["ticket_preview"] is True


def test_scheduler_refuses_live_submission_flag(tmp_path):
    result = CliRunner().invoke(
        app,
        [
            "scheduler",
            "--symbol",
            "SPY",
            "--allow-live-submit",
            "--journal-path",
            str(tmp_path / "journal.jsonl"),
        ],
    )

    assert result.exit_code != 0
    assert "scheduler live submission is not supported" in result.output


def test_scheduler_skips_cycle_when_kill_switch_active(monkeypatch, tmp_path):
    journal_path = tmp_path / "journal.jsonl"
    Journal(journal_path).append(
        JournalEvent(
            event_type="kill_switch_changed",
            decision="enabled",
            payload={"kill_switch_active": True},
        )
    )

    def fail_live_dry_run(**kwargs):
        raise AssertionError("scheduler should not scan when kill switch is active")

    monkeypatch.setattr("tasty_options_bot.cli._is_us_market_hours", lambda: True)
    monkeypatch.setattr("tasty_options_bot.cli.live_dry_run", fail_live_dry_run)

    result = CliRunner().invoke(
        app,
        ["scheduler", "--symbol", "SPY", "--cycles", "1", "--journal-path", str(journal_path)],
    )

    assert result.exit_code == 0
    assert "Kill switch active: True" in result.output
    assert "Skipping scheduler cycle because kill switch is active." in result.output


def test_scheduler_skips_cycle_when_outside_market_hours(monkeypatch, tmp_path):
    calls = []

    def fake_live_dry_run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr("tasty_options_bot.cli._is_us_market_hours", lambda: False)
    monkeypatch.setattr("tasty_options_bot.cli.live_dry_run", fake_live_dry_run)

    result = CliRunner().invoke(
        app,
        ["scheduler", "--symbol", "SPY", "--cycles", "1", "--journal-path", str(tmp_path / "journal.jsonl")],
    )

    assert result.exit_code == 0
    assert "Market hours active: False" in result.output
    assert "Skipping scheduler cycle because market is closed." in result.output
    assert calls == []


def test_is_us_market_hours_uses_new_york_regular_session():
    assert _is_us_market_hours(datetime(2026, 5, 26, 14, 0, tzinfo=timezone.utc)) is True
    assert _is_us_market_hours(datetime(2026, 5, 26, 20, 1, tzinfo=timezone.utc)) is False
    assert _is_us_market_hours(datetime(2026, 5, 23, 14, 0, tzinfo=timezone.utc)) is False


def test_operator_runbook_prints_safe_daily_workflow():
    result = CliRunner().invoke(app, ["operator-runbook"])

    assert result.exit_code == 0
    assert "Safe daily operator runbook" in result.output
    assert "1. Pre-flight readiness" in result.output
    assert ".venv/bin/python -m tasty_options_bot.cli readiness-check --broker-check" in result.output
    assert "2. Reconcile submitted orders" in result.output
    assert "3. Manage open live positions" in result.output
    assert "4. Run dry-run scheduler" in result.output
    assert "5. Manual live submit" in result.output
    assert "No commands in this runbook submit orders except the explicitly manual" in result.output
    assert "live-submit example." in result.output


def test_readiness_check_reports_blockers_without_broker_check(tmp_path):
    journal_path = tmp_path / "journal.jsonl"
    Journal(journal_path).append(
        JournalEvent(
            event_type="kill_switch_changed",
            decision="enabled",
            payload={"kill_switch_active": True},
        )
    )
    Journal(journal_path).append(
        JournalEvent(
            event_type="live_open_order_submitted",
            symbol="SPY",
            decision="submitted",
            payload={"order_response": {"order": {"id": "open-order-123", "status": "Received"}}},
        )
    )

    result = CliRunner().invoke(app, ["readiness-check", "--journal-path", str(journal_path)])

    assert result.exit_code == 0
    assert "Readiness check" in result.output
    assert "Live trading: False" in result.output
    assert "Kill switch active: True" in result.output
    assert "Unresolved submitted opening orders: True" in result.output
    assert "Broker positions: not checked" in result.output
    assert "Live submit readiness: BLOCKED" in result.output
    assert "No orders were placed; readiness-check is read-only." in result.output


def test_readiness_check_reports_broker_positions_when_requested(monkeypatch, tmp_path):
    class FakeClient:
        def get_positions(self):
            return [{"symbol": "SPY   260626P00732000", "quantity": "-1"}]

    monkeypatch.setattr("tasty_options_bot.cli.build_tastytrade_client", lambda: FakeClient())
    monkeypatch.setattr("tasty_options_bot.cli.authenticate_client", lambda client: None)

    result = CliRunner().invoke(
        app,
        ["readiness-check", "--broker-check", "--journal-path", str(tmp_path / "journal.jsonl")],
    )

    assert result.exit_code == 0
    assert "Broker positions checked: True" in result.output
    assert "Broker open positions: True" in result.output
    assert "SPY   260626P00732000" in result.output
    assert "Live submit readiness: BLOCKED" in result.output


def make_decision(action, *, short=725, long=720, credit=0.91, delta=-0.24, reason="passed_strategy_and_risk"):
    return ScannerDecision(
        action=action,
        reason=reason,
        candidate=SpreadCandidate(
            symbol="SPY",
            expiration=date(2026, 7, 16).isoformat(),
            dte=40,
            short_strike=short,
            long_strike=long,
            short_delta=delta,
            credit=credit,
        ),
    )


def test_live_dry_run_accepts_research_only_strategy_and_risk_overrides(monkeypatch):
    class FakeClient:
        session_token = "token"

        def get_nested_option_chain(self, symbol):
            return []

    monkeypatch.setattr("tasty_options_bot.cli.build_tastytrade_client", lambda: FakeClient())
    monkeypatch.setattr("tasty_options_bot.cli.authenticate_client", lambda client: None)

    result = CliRunner().invoke(
        app,
        [
            "live-dry-run",
            "SPY",
            "--spread-width",
            "1",
            "--spread-width",
            "2",
            "--spread-width",
            "5",
            "--min-credit-ratio",
            "0.20",
            "--short-delta-min",
            "0.10",
            "--short-delta-max",
            "0.30",
            "--max-position-loss",
            "425",
            "--max-open-risk",
            "425",
            "--max-open-positions",
            "1",
            "--max-results",
            "10",
        ],
    )

    assert result.exit_code == 0
    assert "No option contracts returned for filters." in result.output


def test_live_dry_run_accepts_preset_and_best_only_options(monkeypatch):
    class FakeClient:
        session_token = "token"

        def get_nested_option_chain(self, symbol):
            return []

    monkeypatch.setattr("tasty_options_bot.cli.build_tastytrade_client", lambda: FakeClient())
    monkeypatch.setattr("tasty_options_bot.cli.authenticate_client", lambda client: None)

    result = CliRunner().invoke(
        app,
        ["live-dry-run", "SPY", "--preset", "five-wide-research", "--best-only"],
    )

    assert result.exit_code == 0
    assert "No option contracts returned for filters." in result.output


def test_live_dry_run_strategy_overrides_allow_researching_five_wide_spreads():
    config = BotConfig()

    strategy = _build_strategy(
        config,
        min_credit_ratio=0.20,
        spread_widths=[1, 2, 5],
        short_delta_min=0.10,
        short_delta_max=0.30,
    )

    assert strategy.config.min_credit_ratio == 0.20
    assert strategy.config.spread_widths == [1, 2, 5]
    assert strategy.config.short_delta_min == 0.10
    assert strategy.config.short_delta_max == 0.30
    assert config.strategy.spread_widths == [1, 2]
    assert config.strategy.min_credit_ratio == 0.25


def test_live_dry_run_risk_overrides_can_gate_five_wide_to_one_position():
    config = BotConfig()

    risk_manager = _build_risk_manager(
        config,
        max_position_loss=425,
        max_open_risk=425,
        max_open_positions=1,
    )

    assert risk_manager.limits.max_position_loss == 425
    assert risk_manager.limits.max_open_risk == 425
    assert risk_manager.limits.max_open_positions == 1
    assert config.account.max_position_loss == 100
    assert config.account.max_open_risk == 400
    assert config.account.max_open_positions == 3


def test_build_risk_manager_uses_config_kill_switch():
    config = BotConfig.model_validate({"execution": {"kill_switch_active": True}})

    risk_manager = _build_risk_manager(config)

    assert risk_manager.limits.kill_switch_active is True


def test_effective_kill_switch_uses_latest_journal_event(tmp_path):
    journal = Journal(tmp_path / "journal.jsonl")
    journal.append(
        JournalEvent(
            event_type="kill_switch_changed",
            decision="enabled",
            reason="operator_requested",
            payload={"kill_switch_active": True},
        )
    )

    assert _effective_kill_switch_active(BotConfig(), journal) is True


def test_kill_switch_cli_enable_disable_and_status(tmp_path):
    journal_path = tmp_path / "journal.jsonl"
    runner = CliRunner()

    enabled = runner.invoke(app, ["kill-switch", "enable", "--journal-path", str(journal_path)])
    status_enabled = runner.invoke(app, ["kill-switch", "status", "--journal-path", str(journal_path)])
    disabled = runner.invoke(app, ["kill-switch", "disable", "--journal-path", str(journal_path)])
    status_disabled = runner.invoke(app, ["kill-switch", "status", "--journal-path", str(journal_path)])

    assert enabled.exit_code == 0
    assert "Kill switch enabled" in enabled.output
    assert status_enabled.exit_code == 0
    assert "Kill switch active: True" in status_enabled.output
    assert disabled.exit_code == 0
    assert "Kill switch disabled" in disabled.output
    assert status_disabled.exit_code == 0
    assert "Kill switch active: False" in status_disabled.output

    events = Journal(journal_path).read_recent(limit=2)
    assert [event.decision for event in events] == ["disabled", "enabled"]


def test_live_dry_run_scanner_config_includes_realized_pnl_loss_totals(tmp_path):
    journal = Journal(tmp_path / "journal.jsonl")
    journal.append(
        JournalEvent(
            event_type="manual_live_trade_closed",
            decision="closed_manually",
            payload={"realized_pnl": -150.0},
            created_at=datetime(2026, 5, 26, 15, 0, tzinfo=timezone.utc),
        )
    )

    scanner_config = _build_scanner_config(
        journal,
        now=datetime(2026, 5, 26, 16, 0, tzinfo=timezone.utc),
        account_equity=3000,
        max_quote_age_seconds=120,
        max_bid_ask_width=0.20,
    )

    assert scanner_config.realized_pnl_today == -150.0
    assert scanner_config.realized_pnl_week == -150.0


def test_five_wide_research_preset_applies_tastytrade_style_dry_run_gates():
    overrides = _apply_live_dry_run_preset(
        preset="five-wide-research",
        spread_width=None,
        min_credit_ratio=None,
        short_delta_min=None,
        short_delta_max=None,
        max_position_loss=None,
        max_open_risk=None,
        max_open_positions=None,
    )

    assert overrides["spread_width"] == [5]
    assert overrides["min_credit_ratio"] == 0.18
    assert overrides["short_delta_min"] == 0.20
    assert overrides["short_delta_max"] == 0.30
    assert overrides["max_position_loss"] == 425
    assert overrides["max_open_risk"] == 425
    assert overrides["max_open_positions"] == 1


def test_explicit_options_override_five_wide_research_preset_values():
    overrides = _apply_live_dry_run_preset(
        preset="five-wide-research",
        spread_width=[1, 5],
        min_credit_ratio=0.20,
        short_delta_min=0.22,
        short_delta_max=0.26,
        max_position_loss=400,
        max_open_risk=400,
        max_open_positions=2,
    )

    assert overrides["spread_width"] == [1, 5]
    assert overrides["min_credit_ratio"] == 0.20
    assert overrides["short_delta_min"] == 0.22
    assert overrides["short_delta_max"] == 0.26
    assert overrides["max_position_loss"] == 400
    assert overrides["max_open_risk"] == 400
    assert overrides["max_open_positions"] == 2


def test_rank_decisions_prioritizes_would_trade_then_credit_ratio_then_lower_risk():
    rejected_high_credit = make_decision(
        "rejected", short=730, long=725, credit=1.10, reason="max_position_loss_exceeded"
    )
    lower_credit_trade = make_decision("would_trade", short=725, long=720, credit=0.91)
    better_trade = make_decision("would_trade", short=726, long=721, credit=0.94)

    ranked = _rank_decisions([rejected_high_credit, lower_credit_trade, better_trade])

    assert ranked == [better_trade, lower_credit_trade, rejected_high_credit]


def test_format_decision_row_includes_expiration_and_dte():
    decision = make_decision("would_trade", short=732, long=727, credit=0.99, delta=-0.30)

    row = _format_decision_row(decision, starting_equity=3000)

    assert row[3] == "2026-07-16"
    assert row[4] == "40"
    assert row[5] == "732.00"
    assert row[6] == "727.00"


def test_format_decision_row_labels_strategy_type():
    decision = make_decision("would_trade", short=732, long=727, credit=0.99, delta=-0.30)

    row = _format_decision_row(decision, starting_equity=3000)

    assert row[2] == "Put Credit Spread"


def test_format_decision_row_includes_order_leg_symbols():
    decision = ScannerDecision(
        action="would_trade",
        reason="passed_strategy_and_risk",
        candidate=SpreadCandidate(
            symbol="SPY",
            expiration=date(2026, 7, 16).isoformat(),
            dte=40,
            short_strike=732,
            long_strike=727,
            short_delta=-0.30,
            credit=0.99,
            short_option_symbol="SPY 260716P00732000",
            long_option_symbol="SPY 260716P00727000",
        ),
    )

    row = _format_decision_row(decision, starting_equity=3000)

    assert row[7] == "SPY 260716P00732000"
    assert row[8] == "SPY 260716P00727000"


def test_build_order_ticket_preview_uses_first_would_trade_decision():
    rejected = make_decision("rejected", reason="max_position_loss_exceeded")
    allowed = ScannerDecision(
        action="would_trade",
        reason="passed_strategy_and_risk",
        candidate=SpreadCandidate(
            symbol="SPY",
            expiration=date(2026, 7, 16).isoformat(),
            dte=40,
            short_strike=732,
            long_strike=727,
            short_delta=-0.30,
            credit=0.99,
            short_option_symbol="SPY 260716P00732000",
            long_option_symbol="SPY 260716P00727000",
        ),
    )

    ticket = _build_order_ticket_preview([rejected, allowed], starting_equity=3000)

    assert ticket is not None
    assert ticket.strategy == "Put Credit Spread"
    assert ticket.legs[0].option_symbol == "SPY 260716P00732000"
    assert ticket.safety_status == "preview_only_not_submitted"
    assert ticket.submission_allowed is False


def _patch_live_dry_run_would_trade(monkeypatch):
    from types import SimpleNamespace
    from datetime import timedelta
    from tasty_options_bot.option_chain import OptionQuote

    now = datetime.now(timezone.utc)
    expiration = (now + timedelta(days=40)).date()
    contracts = [
        SimpleNamespace(option_symbol="SPY   260705P00100000"),
        SimpleNamespace(option_symbol="SPY   260705P00099000"),
    ]
    quotes = [
        OptionQuote(
            symbol="SPY",
            expiration=expiration,
            option_type="put",
            strike=100.0,
            delta=-0.20,
            bid=0.45,
            ask=0.47,
            quote_time=now,
            option_symbol="SPY   260705P00100000",
        ),
        OptionQuote(
            symbol="SPY",
            expiration=expiration,
            option_type="put",
            strike=99.0,
            delta=-0.10,
            bid=0.15,
            ask=0.17,
            quote_time=now,
            option_symbol="SPY   260705P00099000",
        ),
    ]
    monkeypatch.setattr("tasty_options_bot.cli.parse_nested_option_chain", lambda *args, **kwargs: contracts)
    monkeypatch.setattr("tasty_options_bot.cli.parse_equity_option_market_data", lambda *args, **kwargs: quotes)


class _OpeningSubmitFakeClient:
    def __init__(self):
        self.submissions = []
        self.position_calls = 0

    def get_nested_option_chain(self, symbol):
        return [{"ignored": True}]

    def get_equity_option_market_data(self, symbols):
        return [{"ignored": True, "symbols": symbols}]

    def get_positions(self):
        self.position_calls += 1
        return []

    def submit_order_payload(self, payload, *, approved):
        self.submissions.append({"payload": payload, "approved": approved})
        return {"order": {"id": "open-order-123", "status": "Received"}}


def test_live_dry_run_submit_open_requires_explicit_acknowledgement(monkeypatch, tmp_path):
    _patch_live_dry_run_would_trade(monkeypatch)
    fake_client = _OpeningSubmitFakeClient()
    monkeypatch.setattr("tasty_options_bot.cli.build_tastytrade_client", lambda: fake_client)
    monkeypatch.setattr("tasty_options_bot.cli.authenticate_client", lambda client: None)

    result = CliRunner().invoke(
        app,
        [
            "live-dry-run",
            "SPY",
            "--submit-open",
            "--confirm-symbol",
            "SPY",
            "--journal-path",
            str(tmp_path / "journal.jsonl"),
        ],
    )

    assert result.exit_code != 0
    assert "--submit-open requires --i-understand-live-order" in result.output
    assert fake_client.submissions == []


def test_live_dry_run_submit_open_posts_best_would_trade_only_after_all_confirmations(monkeypatch, tmp_path):
    _patch_live_dry_run_would_trade(monkeypatch)
    journal_path = tmp_path / "journal.jsonl"
    fake_client = _OpeningSubmitFakeClient()
    monkeypatch.setattr("tasty_options_bot.cli.build_tastytrade_client", lambda: fake_client)
    monkeypatch.setattr("tasty_options_bot.cli.authenticate_client", lambda client: None)

    result = CliRunner().invoke(
        app,
        [
            "live-dry-run",
            "SPY",
            "--submit-open",
            "--i-understand-live-order",
            "--confirm-symbol",
            "SPY",
            "--max-entry-leg-bid-ask-width",
            "0.05",
            "--journal-path",
            str(journal_path),
        ],
    )

    assert result.exit_code == 0
    assert "LIVE OPEN ORDER SUBMITTED" in result.output
    assert "Order id: open-order-123" in result.output
    assert fake_client.position_calls == 1
    assert fake_client.submissions == [
        {
            "approved": True,
            "payload": {
                "order-type": "Limit",
                "time-in-force": "Day",
                "price-effect": "Credit",
                "price": "0.30",
                "source": "tasty-options-bot-preview",
                "legs": [
                    {
                        "action": "Sell to Open",
                        "instrument-type": "Equity Option",
                        "symbol": "SPY   260705P00100000",
                        "quantity": 1,
                    },
                    {
                        "action": "Buy to Open",
                        "instrument-type": "Equity Option",
                        "symbol": "SPY   260705P00099000",
                        "quantity": 1,
                    },
                ],
            },
        }
    ]
    submitted = next(event for event in Journal(journal_path).read_recent(limit=20) if event.event_type == "live_open_order_submitted")
    assert submitted.decision == "submitted"
    assert submitted.payload["order_response"] == {"order": {"id": "open-order-123", "status": "Received"}}
    assert submitted.payload["candidate"]["short_option_symbol"] == "SPY   260705P00100000"
    assert submitted.payload["candidate"]["strategy"] == "Put Credit Spread"


def test_live_dry_run_submit_open_refuses_when_live_positions_exist(monkeypatch, tmp_path):
    _patch_live_dry_run_would_trade(monkeypatch)

    class FakeClient(_OpeningSubmitFakeClient):
        def get_positions(self):
            return [{"symbol": "QQQ   260705P00400000", "quantity": "-1"}]

        def submit_order_payload(self, payload, *, approved):
            raise AssertionError("open submit must be blocked when broker has live positions")

    monkeypatch.setattr("tasty_options_bot.cli.build_tastytrade_client", lambda: FakeClient())
    monkeypatch.setattr("tasty_options_bot.cli.authenticate_client", lambda client: None)

    result = CliRunner().invoke(
        app,
        [
            "live-dry-run",
            "SPY",
            "--submit-open",
            "--i-understand-live-order",
            "--confirm-symbol",
            "SPY",
            "--journal-path",
            str(tmp_path / "journal.jsonl"),
        ],
    )

    assert result.exit_code != 0
    assert "submit-open blocked: broker has live positions" in result.output


def test_live_dry_run_submit_open_refuses_when_kill_switch_enabled(monkeypatch, tmp_path):
    _patch_live_dry_run_would_trade(monkeypatch)
    journal_path = tmp_path / "journal.jsonl"
    Journal(journal_path).append(
        JournalEvent(
            event_type="kill_switch_changed",
            decision="enabled",
            reason="operator_requested",
            payload={"kill_switch_active": True},
        )
    )
    fake_client = _OpeningSubmitFakeClient()
    monkeypatch.setattr("tasty_options_bot.cli.build_tastytrade_client", lambda: fake_client)
    monkeypatch.setattr("tasty_options_bot.cli.authenticate_client", lambda client: None)

    result = CliRunner().invoke(
        app,
        [
            "live-dry-run",
            "SPY",
            "--submit-open",
            "--i-understand-live-order",
            "--confirm-symbol",
            "SPY",
            "--journal-path",
            str(journal_path),
        ],
    )

    assert result.exit_code != 0
    assert "kill_switch_active" in result.output
    assert fake_client.submissions == []


def test_risk_status_prints_effective_journal_kill_switch_state(tmp_path):
    journal_path = tmp_path / "journal.jsonl"
    Journal(journal_path).append(
        JournalEvent(
            event_type="kill_switch_changed",
            decision="enabled",
            reason="operator_requested",
            payload={"kill_switch_active": True},
        )
    )

    result = CliRunner().invoke(app, ["risk-status", "--journal-path", str(journal_path)])

    assert result.exit_code == 0
    assert "Kill switch active: True" in result.output


def test_live_dry_run_submit_open_refuses_when_prior_open_order_unresolved(monkeypatch, tmp_path):
    _patch_live_dry_run_would_trade(monkeypatch)
    journal_path = tmp_path / "journal.jsonl"
    Journal(journal_path).append(
        JournalEvent(
            event_type="live_open_order_submitted",
            symbol="SPY",
            decision="submitted",
            reason="passed_strategy_and_risk",
            payload={"order_response": {"order": {"id": "open-order-existing", "status": "Received"}}},
        )
    )
    fake_client = _OpeningSubmitFakeClient()
    monkeypatch.setattr("tasty_options_bot.cli.build_tastytrade_client", lambda: fake_client)
    monkeypatch.setattr("tasty_options_bot.cli.authenticate_client", lambda client: None)

    result = CliRunner().invoke(
        app,
        [
            "live-dry-run",
            "SPY",
            "--submit-open",
            "--i-understand-live-order",
            "--confirm-symbol",
            "SPY",
            "--journal-path",
            str(journal_path),
        ],
    )

    assert result.exit_code != 0
    assert "submit-open blocked: unresolved live opening order exists" in result.output
    assert fake_client.position_calls == 0
    assert fake_client.submissions == []
