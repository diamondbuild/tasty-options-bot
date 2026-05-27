from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from tasty_options_bot.journal import Journal, realized_pnl_totals

OPEN_POSITION_EVENTS = {"manual_live_trade_entered", "live_open_order_filled"}
CLOSE_POSITION_EVENTS = {"manual_live_trade_closed", "live_close_order_filled"}
SUBMITTED_ORDER_EVENTS = {"live_open_order_submitted", "live_close_order_submitted"}
SCANNER_EVENT_TYPES = {"scanner_decision", "dry_run_scanner_decision"}


@dataclass(frozen=True)
class OperatorReport:
    report_date: date
    account_equity: float | None = None
    realized_pnl_today: float = 0.0
    realized_pnl_week: float = 0.0
    unrealized_pnl: float | None = None
    open_risk: float = 0.0
    open_positions: int = 0
    candidates_found: int = 0
    rejected_candidates: dict[str, int] = field(default_factory=dict)
    orders_submitted: int = 0
    kill_switch_active: bool = False
    readiness_blockers: list[str] = field(default_factory=list)

    @property
    def readiness(self) -> str:
        return "BLOCKED" if self.readiness_blockers else "READY"

    def to_text(self) -> str:
        lines = [
            "Daily operator report",
            f"Date: {self.report_date.isoformat()}",
            f"Account equity: {_format_money_optional(self.account_equity)}",
            f"Realized P/L today: {_format_money(self.realized_pnl_today)}",
            f"Realized P/L week: {_format_money(self.realized_pnl_week)}",
            f"Unrealized P/L: {_format_money_optional(self.unrealized_pnl)}",
            f"Open risk: {_format_money(self.open_risk)}",
            f"Open positions: {self.open_positions}",
            f"Candidates found: {self.candidates_found}",
            "Rejected candidates:",
        ]
        if self.rejected_candidates:
            lines.extend(f"- {reason}: {count}" for reason, count in sorted(self.rejected_candidates.items()))
        else:
            lines.append("- none")
        lines.extend(
            [
                f"Orders submitted: {self.orders_submitted}",
                f"Kill switch active: {self.kill_switch_active}",
                f"Readiness: {self.readiness}",
                "Readiness blockers:",
            ]
        )
        if self.readiness_blockers:
            lines.extend(f"- {blocker}" for blocker in self.readiness_blockers)
        else:
            lines.append("- none")
        return "\n".join(lines)

    def to_markdown(self) -> str:
        text = self.to_text().splitlines()
        return "# " + "\n".join(text) + "\n"


def build_operator_report(
    journal: Journal,
    *,
    today: date,
    account_equity: float | None = None,
    unrealized_pnl: float | None = None,
) -> OperatorReport:
    events = list(reversed(journal.read_recent(limit=10000)))
    totals = realized_pnl_totals(journal, today=today)
    closed_position_ids = _closed_position_ids(events)
    open_positions = []
    for event in events:
        if event.event_type not in OPEN_POSITION_EVENTS:
            continue
        position_id = _position_id(event)
        if position_id in closed_position_ids:
            continue
        if any(_position_id(existing) == position_id for existing in open_positions):
            continue
        open_positions.append(event)

    rejected_candidates: dict[str, int] = {}
    candidates_found = 0
    for event in events:
        if event.event_type not in SCANNER_EVENT_TYPES:
            continue
        if event.decision == "would_trade":
            candidates_found += 1
        elif event.decision == "rejected":
            rejected_candidates[event.reason or "unknown"] = rejected_candidates.get(event.reason or "unknown", 0) + 1

    kill_switch_active = False
    for event in reversed(events):
        if event.event_type == "kill_switch_changed":
            state = event.payload.get("kill_switch_active")
            if isinstance(state, bool):
                kill_switch_active = state
            break

    open_risk = round(sum(_event_open_risk(event) for event in open_positions), 2)
    orders_submitted = sum(1 for event in events if event.event_type in SUBMITTED_ORDER_EVENTS)
    readiness_blockers = _readiness_blockers(
        kill_switch_active=kill_switch_active,
        open_positions=len(open_positions),
        orders_submitted=orders_submitted,
    )
    return OperatorReport(
        report_date=today,
        account_equity=account_equity,
        realized_pnl_today=totals.today,
        realized_pnl_week=totals.week,
        unrealized_pnl=unrealized_pnl,
        open_risk=open_risk,
        open_positions=len(open_positions),
        candidates_found=candidates_found,
        rejected_candidates=rejected_candidates,
        orders_submitted=orders_submitted,
        kill_switch_active=kill_switch_active,
        readiness_blockers=readiness_blockers,
    )


def write_markdown_report(report: OperatorReport, reports_dir: str | Path = "reports") -> Path:
    directory = Path(reports_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"operator-report-{report.report_date.isoformat()}.md"
    path.write_text(report.to_markdown(), encoding="utf-8")
    return path


def _format_money(value: float) -> str:
    return f"${value:,.2f}"


def _format_money_optional(value: float | None) -> str:
    if value is None:
        return "n/a"
    return _format_money(value)


def _closed_position_ids(events) -> set[str]:
    ids = set()
    for event in events:
        if event.event_type not in CLOSE_POSITION_EVENTS:
            continue
        position_id = _position_id(event)
        if position_id:
            ids.add(position_id)
    return ids


def _position_id(event) -> str:
    position_id = event.payload.get("position_id")
    if position_id:
        return str(position_id)
    symbol = event.symbol or str(event.payload.get("symbol", ""))
    expiration = str(event.payload.get("expiration", ""))
    short_symbol = str(event.payload.get("short_option_symbol", ""))
    long_symbol = str(event.payload.get("long_option_symbol", ""))
    return ":".join([symbol, expiration, short_symbol, long_symbol])


def _event_open_risk(event) -> float:
    for key in ("max_loss", "open_risk"):
        value = event.payload.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
    short_strike = event.payload.get("short_strike")
    long_strike = event.payload.get("long_strike")
    credit = event.payload.get("opening_credit", event.payload.get("credit"))
    quantity = event.payload.get("quantity", 1)
    try:
        width = abs(float(short_strike) - float(long_strike))
        return round((width - float(credit)) * 100 * int(quantity), 2)
    except (TypeError, ValueError):
        return 0.0


def _readiness_blockers(*, kill_switch_active: bool, open_positions: int, orders_submitted: int) -> list[str]:
    blockers = []
    if kill_switch_active:
        blockers.append("kill_switch_active")
    if open_positions:
        blockers.append("open_positions_present")
    if orders_submitted:
        blockers.append("submitted_orders_present")
    return blockers
