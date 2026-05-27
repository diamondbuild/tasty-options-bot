from datetime import date, datetime, timezone

from tasty_options_bot.journal import Journal
from tasty_options_bot.option_chain import OptionQuote
from tasty_options_bot.risk import AccountRiskLimits, RiskManager
from tasty_options_bot.scanner import DryRunScanner, ScannerConfig, ScannerDecision
from tasty_options_bot.strategy import PutCreditSpreadStrategy, StrategyConfig


def make_quote(**overrides):
    data = {
        "symbol": "SPY",
        "expiration": date(2026, 7, 16),
        "strike": 100.0,
        "option_type": "put",
        "bid": 0.30,
        "ask": 0.34,
        "delta": -0.20,
        "quote_time": datetime(2026, 6, 1, 14, 30, tzinfo=timezone.utc),
    }
    data.update(overrides)
    return OptionQuote(**data)


def make_scanner(tmp_path):
    strategy = PutCreditSpreadStrategy(
        StrategyConfig(
            universe=["SPY"],
            dte_min=30,
            dte_max=45,
            short_delta_min=0.15,
            short_delta_max=0.25,
            spread_widths=[1],
            min_credit_ratio=0.25,
        )
    )
    risk = RiskManager(AccountRiskLimits(max_position_loss=100, max_open_risk=400, max_open_positions=3))
    journal = Journal(tmp_path / "journal.jsonl")
    return DryRunScanner(strategy=strategy, risk_manager=risk, journal=journal), journal


def test_scanner_marks_valid_candidate_as_would_trade_and_journals_it(tmp_path):
    scanner, journal = make_scanner(tmp_path)
    quotes = [
        make_quote(strike=100, bid=0.30, ask=0.34, delta=-0.20),
        make_quote(strike=99, bid=0.02, ask=0.04, delta=-0.10),
    ]

    decisions = scanner.scan(
        quotes,
        config=ScannerConfig(today=date(2026, 6, 1), now=datetime(2026, 6, 1, 14, 31, tzinfo=timezone.utc)),
    )

    assert len(decisions) == 1
    assert decisions[0].action == "would_trade"
    assert decisions[0].reason == "passed_strategy_and_risk"
    assert decisions[0].candidate.symbol == "SPY"
    events = journal.read_recent()
    assert len(events) == 1
    assert events[0].event_type == "scanner_decision"
    assert events[0].decision == "would_trade"
    assert events[0].reason == "passed_strategy_and_risk"


def test_scanner_rejects_strategy_failures_and_journals_reason(tmp_path):
    scanner, journal = make_scanner(tmp_path)
    quotes = [
        make_quote(strike=100, bid=0.10, ask=0.12, delta=-0.20),
        make_quote(strike=99, bid=0.02, ask=0.04, delta=-0.10),
    ]

    decisions = scanner.scan(
        quotes,
        config=ScannerConfig(today=date(2026, 6, 1), now=datetime(2026, 6, 1, 14, 31, tzinfo=timezone.utc)),
    )

    assert len(decisions) == 1
    assert decisions[0].action == "rejected"
    assert decisions[0].reason == "min_credit_ratio_not_met"
    assert journal.read_recent()[0].reason == "min_credit_ratio_not_met"


def test_scanner_rejects_risk_failures(tmp_path):
    strategy = PutCreditSpreadStrategy(
        StrategyConfig(universe=["SPY"], spread_widths=[2], min_credit_ratio=0.25)
    )
    risk = RiskManager(AccountRiskLimits(max_position_loss=50, max_open_risk=400, max_open_positions=3))
    journal = Journal(tmp_path / "journal.jsonl")
    scanner = DryRunScanner(strategy=strategy, risk_manager=risk, journal=journal)
    quotes = [
        make_quote(strike=100, bid=0.60, ask=0.64, delta=-0.20),
        make_quote(strike=98, bid=0.02, ask=0.04, delta=-0.10),
    ]

    decisions = scanner.scan(
        quotes,
        config=ScannerConfig(today=date(2026, 6, 1), now=datetime(2026, 6, 1, 14, 31, tzinfo=timezone.utc)),
    )

    assert decisions[0].action == "rejected"
    assert decisions[0].reason == "max_position_loss_exceeded"


def test_scanner_rejects_daily_loss_limit_from_config(tmp_path):
    strategy = PutCreditSpreadStrategy(StrategyConfig(universe=["SPY"], spread_widths=[1], min_credit_ratio=0.25))
    risk = RiskManager(
        AccountRiskLimits(
            max_position_loss=100,
            max_open_risk=400,
            max_open_positions=3,
            max_daily_loss=150,
        )
    )
    journal = Journal(tmp_path / "journal.jsonl")
    scanner = DryRunScanner(strategy=strategy, risk_manager=risk, journal=journal)
    quotes = [
        make_quote(strike=100, bid=0.30, ask=0.34, delta=-0.20),
        make_quote(strike=99, bid=0.02, ask=0.04, delta=-0.10),
    ]

    decisions = scanner.scan(
        quotes,
        config=ScannerConfig(
            now=datetime(2026, 6, 1, 14, 31, tzinfo=timezone.utc),
            realized_pnl_today=-150,
        ),
    )

    assert decisions[0].action == "rejected"
    assert decisions[0].reason == "max_daily_loss_reached"


def test_scanner_decision_converts_to_journal_event():
    decision = ScannerDecision(action="rejected", reason="symbol_not_in_universe", candidate=None)

    event = decision.to_journal_event()

    assert event.event_type == "scanner_decision"
    assert event.decision == "rejected"
    assert event.reason == "symbol_not_in_universe"
