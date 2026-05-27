import json
from datetime import date, datetime, timezone

from tasty_options_bot.journal import Journal, JournalEvent, realized_pnl_totals


def test_journal_appends_jsonl_events(tmp_path):
    path = tmp_path / "journal.jsonl"
    journal = Journal(path)
    event = JournalEvent(
        event_type="risk_decision",
        symbol="SPY",
        decision="rejected",
        reason="max_open_risk_exceeded",
        payload={"max_open_risk": 400, "candidate_risk": 150},
        created_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
    )

    journal.append(event)

    lines = path.read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["event_type"] == "risk_decision"
    assert record["symbol"] == "SPY"
    assert record["decision"] == "rejected"
    assert record["reason"] == "max_open_risk_exceeded"
    assert record["payload"] == {"max_open_risk": 400, "candidate_risk": 150}
    assert record["created_at"] == "2026-01-02T03:04:05+00:00"


def test_journal_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "audit" / "journal.jsonl"
    journal = Journal(path)

    journal.append(JournalEvent(event_type="login_check", decision="ok"))

    assert path.exists()


def test_journal_reads_events_newest_first_with_limit(tmp_path):
    path = tmp_path / "journal.jsonl"
    journal = Journal(path)
    journal.append(JournalEvent(event_type="one", decision="ok"))
    journal.append(JournalEvent(event_type="two", decision="ok"))
    journal.append(JournalEvent(event_type="three", decision="ok"))

    events = journal.read_recent(limit=2)

    assert [event.event_type for event in events] == ["three", "two"]


def test_journal_read_recent_returns_empty_for_missing_file(tmp_path):
    journal = Journal(tmp_path / "missing.jsonl")

    assert journal.read_recent() == []


def test_realized_pnl_totals_sum_closed_trade_events_by_day_and_week(tmp_path):
    journal = Journal(tmp_path / "journal.jsonl")
    journal.append(
        JournalEvent(
            event_type="manual_live_trade_closed",
            decision="closed_manually",
            payload={"realized_pnl": -60.0},
            created_at=datetime(2026, 5, 25, 14, 0, tzinfo=timezone.utc),
        )
    )
    journal.append(
        JournalEvent(
            event_type="live_close_order_filled",
            decision="filled",
            payload={"realized_pnl": -90.0},
            created_at=datetime(2026, 5, 26, 14, 0, tzinfo=timezone.utc),
        )
    )
    journal.append(
        JournalEvent(
            event_type="manual_live_trade_closed",
            decision="closed_manually",
            payload={"realized_pnl": 25.0},
            created_at=datetime(2026, 5, 19, 14, 0, tzinfo=timezone.utc),
        )
    )

    totals = realized_pnl_totals(journal, today=date(2026, 5, 26))

    assert totals.today == -90.0
    assert totals.week == -150.0


def test_journal_rejects_empty_event_type():
    event = JournalEvent(event_type="", decision="ok")

    assert event.is_valid is False
