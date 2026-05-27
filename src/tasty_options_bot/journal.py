from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class JournalEvent:
    event_type: str
    decision: str
    symbol: str = ""
    reason: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_valid(self) -> bool:
        return bool(self.event_type.strip()) and bool(self.decision.strip())

    def to_record(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at.isoformat(),
            "event_type": self.event_type,
            "symbol": self.symbol,
            "decision": self.decision,
            "reason": self.reason,
            "payload": self.payload,
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> JournalEvent:
        created_at_raw = record.get("created_at")
        created_at = (
            datetime.fromisoformat(created_at_raw)
            if isinstance(created_at_raw, str) and created_at_raw
            else datetime.now(timezone.utc)
        )
        return cls(
            event_type=str(record.get("event_type", "")),
            symbol=str(record.get("symbol", "")),
            decision=str(record.get("decision", "")),
            reason=str(record.get("reason", "")),
            payload=record.get("payload", {}) if isinstance(record.get("payload", {}), dict) else {},
            created_at=created_at,
        )


@dataclass(frozen=True)
class RealizedPnlTotals:
    today: float
    week: float


class Journal:
    def __init__(self, path: str | Path = "data/journal.jsonl") -> None:
        self.path = Path(path)

    def append(self, event: JournalEvent) -> None:
        if not event.is_valid:
            raise ValueError("journal event requires event_type and decision")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event.to_record(), sort_keys=True) + "\n")

    def read_recent(self, limit: int = 20) -> list[JournalEvent]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        records = []
        for line in reversed(lines[-limit:]):
            if not line.strip():
                continue
            records.append(JournalEvent.from_record(json.loads(line)))
        return records


def realized_pnl_totals(journal: Journal, *, today: date) -> RealizedPnlTotals:
    week_start = today - timedelta(days=today.weekday())
    daily_total = 0.0
    weekly_total = 0.0
    for event in journal.read_recent(limit=10000):
        realized_pnl = event.payload.get("realized_pnl")
        if realized_pnl is None:
            continue
        try:
            pnl = float(realized_pnl)
        except (TypeError, ValueError):
            continue

        event_date = event.created_at.date()
        if event_date == today:
            daily_total += pnl
        if week_start <= event_date <= today:
            weekly_total += pnl
    return RealizedPnlTotals(today=round(daily_total, 2), week=round(weekly_total, 2))
