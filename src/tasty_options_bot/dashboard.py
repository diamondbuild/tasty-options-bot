from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tasty_options_bot.config import BotConfig, load_config
from tasty_options_bot.journal import Journal, JournalEvent
from tasty_options_bot.reports import build_operator_report, OperatorReport

OPEN_POSITION_EVENTS = {"manual_live_trade_entered", "live_open_order_filled"}
CLOSE_POSITION_EVENTS = {"manual_live_trade_closed", "live_close_order_filled"}


@dataclass(frozen=True)
class DashboardSafety:
    live_trading: bool
    manual_approval_required: bool
    market_orders_allowed: bool
    kill_switch_active: bool


@dataclass(frozen=True)
class DashboardPosition:
    position_id: str
    symbol: str
    strategy_type: str
    short_option_symbol: str
    long_option_symbol: str
    opening_credit: float | None
    max_loss: float | None


@dataclass(frozen=True)
class DashboardExitDecision:
    symbol: str
    decision: str
    reason: str
    estimated_debit_to_close: float | None
    pnl_if_closed: float | None
    dte: int | None
    created_at: str


@dataclass(frozen=True)
class DashboardSnapshot:
    report: OperatorReport
    safety: DashboardSafety
    open_positions: list[DashboardPosition]
    latest_exit_decision: DashboardExitDecision | None
    recent_events: list[JournalEvent]


class DashboardServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler_class, *, journal_path: Path) -> None:
        super().__init__(server_address, handler_class)
        self.journal_path = journal_path


def build_dashboard_snapshot(*, config: BotConfig, journal: Journal, today: date) -> DashboardSnapshot:
    events = list(reversed(journal.read_recent(limit=10000)))
    report = build_operator_report(journal, today=today)
    kill_switch_active = _latest_kill_switch_state(events, default=config.execution.kill_switch_active)
    return DashboardSnapshot(
        report=report,
        safety=DashboardSafety(
            live_trading=config.execution.live_trading,
            manual_approval_required=config.execution.require_manual_approval,
            market_orders_allowed=config.execution.allow_market_orders,
            kill_switch_active=kill_switch_active,
        ),
        open_positions=_open_positions_from_events(events),
        latest_exit_decision=_latest_exit_decision(events),
        recent_events=list(reversed(events[-25:])),
    )


def make_dashboard_handler(*, config_dir: Path | str = "config"):
    class LocalDashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path not in {"/", "/index.html"}:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found")
                return
            server = self.server
            journal_path = getattr(server, "journal_path")
            snapshot = build_dashboard_snapshot(
                config=load_config(config_dir),
                journal=Journal(journal_path),
                today=date.today(),
            )
            body = render_dashboard_html(snapshot).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            return

    return LocalDashboardHandler


def serve_dashboard(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    journal_path: Path | str = "data/journal.jsonl",
    config_dir: Path | str = "config",
) -> DashboardServer:
    handler = make_dashboard_handler(config_dir=config_dir)
    server = DashboardServer((host, port), handler, journal_path=Path(journal_path))
    server.serve_forever()
    return server


def render_dashboard_html(snapshot: DashboardSnapshot) -> str:
    report = snapshot.report
    readiness_class = "blocked" if report.readiness == "BLOCKED" else "ready"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Tasty Options Bot Dashboard</title>
  <style>{_css()}</style>
</head>
<body>
  <header>
    <div>
      <p class="eyebrow">Mode: Read-only Local Dashboard</p>
      <h1>Tasty Options Bot Dashboard</h1>
      <p class="muted">No orders can be submitted from this dashboard. Use it to monitor risk, journal history, and the current open trade while the CLI remains the execution gate.</p>
    </div>
    <div class="status {readiness_class}">{escape(report.readiness)}</div>
  </header>

  <main>
    <section class="grid cards">
      {_metric_card("Open Risk", _money(report.open_risk))}
      {_metric_card("Open Positions", str(report.open_positions))}
      {_metric_card("Realized P/L Today", _money(report.realized_pnl_today))}
      {_metric_card("Realized P/L Week", _money(report.realized_pnl_week))}
    </section>

    <section class="panel">
      <h2>Safety Controls</h2>
      <div class="pill-row">
        {_safety_pill("Live Trading Disabled", not snapshot.safety.live_trading)}
        {_safety_pill("Manual Approval Required", snapshot.safety.manual_approval_required)}
        {_safety_pill("Market Orders Disabled", not snapshot.safety.market_orders_allowed)}
        {_safety_pill("Kill Switch Active", snapshot.safety.kill_switch_active, danger=True)}
      </div>
      <p class="muted">Dashboard controls are intentionally display-only in this phase. Manual/auto mode toggles will be added only after backend permission gates and tests exist.</p>
    </section>

    <section class="grid two">
      <article class="panel">
        <h2>Open Positions</h2>
        {_positions_table(snapshot.open_positions)}
      </article>
      <article class="panel">
        <h2>Latest Exit Guidance</h2>
        {_exit_decision(snapshot.latest_exit_decision)}
      </article>
    </section>

    <section class="panel">
      <h2>Journal &amp; History</h2>
      {_journal_table(snapshot.recent_events)}
    </section>
  </main>
</body>
</html>"""


def _open_positions_from_events(events: list[JournalEvent]) -> list[DashboardPosition]:
    closed_ids = {
        _position_id(event)
        for event in events
        if event.event_type in CLOSE_POSITION_EVENTS and _position_id(event)
    }
    positions = []
    seen = set()
    for event in events:
        if event.event_type not in OPEN_POSITION_EVENTS:
            continue
        position_id = _position_id(event)
        if not position_id or position_id in closed_ids or position_id in seen:
            continue
        seen.add(position_id)
        payload = event.payload
        positions.append(
            DashboardPosition(
                position_id=position_id,
                symbol=event.symbol or str(payload.get("symbol", "")),
                strategy_type=str(payload.get("strategy_type") or payload.get("strategy") or "Put Credit Spread"),
                short_option_symbol=str(payload.get("short_option_symbol", "")),
                long_option_symbol=str(payload.get("long_option_symbol", "")),
                opening_credit=_optional_float(payload.get("opening_credit", payload.get("credit"))),
                max_loss=_optional_float(payload.get("max_loss", payload.get("open_risk"))),
            )
        )
    return positions


def _latest_exit_decision(events: list[JournalEvent]) -> DashboardExitDecision | None:
    for event in reversed(events):
        if event.event_type != "exit_decision":
            continue
        payload = event.payload
        return DashboardExitDecision(
            symbol=event.symbol,
            decision=event.decision,
            reason=event.reason,
            estimated_debit_to_close=_optional_float(payload.get("estimated_debit_to_close")),
            pnl_if_closed=_optional_float(payload.get("pnl_if_closed", payload.get("realized_pnl_if_closed"))),
            dte=_optional_int(payload.get("dte")),
            created_at=event.created_at.isoformat(),
        )
    return None


def _latest_kill_switch_state(events: list[JournalEvent], *, default: bool) -> bool:
    for event in reversed(events):
        if event.event_type != "kill_switch_changed":
            continue
        state = event.payload.get("kill_switch_active")
        if isinstance(state, bool):
            return state
    return bool(default)


def _position_id(event: JournalEvent) -> str:
    position_id = event.payload.get("position_id")
    if position_id:
        return str(position_id)
    symbol = event.symbol or str(event.payload.get("symbol", ""))
    expiration = str(event.payload.get("expiration", ""))
    short_symbol = str(event.payload.get("short_option_symbol", ""))
    long_symbol = str(event.payload.get("long_option_symbol", ""))
    return ":".join([symbol, expiration, short_symbol, long_symbol])


def _positions_table(positions: list[DashboardPosition]) -> str:
    if not positions:
        return '<p class="muted">No open journaled positions.</p>'
    rows = "".join(
        "<tr>"
        f"<td>{escape(position.position_id)}</td>"
        f"<td>{escape(position.symbol)}</td>"
        f"<td>{escape(position.strategy_type)}</td>"
        f"<td>{escape(position.short_option_symbol)}</td>"
        f"<td>{escape(position.long_option_symbol)}</td>"
        f"<td>{_money_optional(position.opening_credit)}</td>"
        f"<td>{_money_optional(position.max_loss)}</td>"
        "</tr>"
        for position in positions
    )
    return f"""<div class="table-wrap"><table>
      <thead><tr><th>Position ID</th><th>Symbol</th><th>Strategy</th><th>Short Leg</th><th>Long Leg</th><th>Credit</th><th>Max Loss</th></tr></thead>
      <tbody>{rows}</tbody>
    </table></div>"""


def _exit_decision(decision: DashboardExitDecision | None) -> str:
    if decision is None:
        return '<p class="muted">No exit guidance recorded yet.</p>'
    return f"""<dl class="details">
      <dt>Symbol</dt><dd>{escape(decision.symbol)}</dd>
      <dt>Action</dt><dd>{escape(decision.decision)}</dd>
      <dt>Reason</dt><dd>{escape(decision.reason)}</dd>
      <dt>Estimated debit to close</dt><dd>{_money_optional(decision.estimated_debit_to_close)}</dd>
      <dt>P/L if closed</dt><dd>{_money_optional(decision.pnl_if_closed)}</dd>
      <dt>DTE</dt><dd>{'' if decision.dte is None else decision.dte}</dd>
      <dt>Recorded</dt><dd>{escape(decision.created_at)}</dd>
    </dl>"""


def _journal_table(events: list[JournalEvent]) -> str:
    if not events:
        return '<p class="muted">No journal events found.</p>'
    rows = "".join(
        "<tr>"
        f"<td>{escape(event.created_at.isoformat())}</td>"
        f"<td>{escape(event.event_type)}</td>"
        f"<td>{escape(event.symbol)}</td>"
        f"<td>{escape(event.decision)}</td>"
        f"<td>{escape(event.reason)}</td>"
        "</tr>"
        for event in events
    )
    return f"""<div class="table-wrap"><table>
      <thead><tr><th>Time</th><th>Type</th><th>Symbol</th><th>Decision</th><th>Reason</th></tr></thead>
      <tbody>{rows}</tbody>
    </table></div>"""


def _metric_card(label: str, value: str) -> str:
    return f'<article class="card"><span>{escape(label)}</span><strong>{escape(value)}</strong></article>'


def _safety_pill(label: str, enabled: bool, *, danger: bool = False) -> str:
    css_class = "danger" if danger and enabled else "good" if enabled else "neutral"
    state = "ON" if enabled else "OFF"
    return f'<span class="pill {css_class}">{escape(label)}: {state}</span>'


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _money_optional(value: float | None) -> str:
    if value is None:
        return "n/a"
    return _money(value)


def _optional_float(value) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _optional_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _css() -> str:
    return """
    :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0b1020; color: #e6edf7; }
    * { box-sizing: border-box; }
    body { margin: 0; background: radial-gradient(circle at top left, #1d2b53, #0b1020 42%); min-height: 100vh; }
    header, main { max-width: 1180px; margin: 0 auto; padding: 28px; }
    header { display: flex; align-items: center; justify-content: space-between; gap: 24px; }
    h1 { font-size: clamp(2rem, 5vw, 4.2rem); line-height: 1; margin: 0 0 14px; }
    h2 { margin: 0 0 18px; }
    .eyebrow { color: #7dd3fc; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
    .muted { color: #9fb0ca; }
    .status { border-radius: 999px; padding: 12px 18px; font-weight: 800; }
    .status.blocked { background: #451a03; color: #fdba74; border: 1px solid #f97316; }
    .status.ready { background: #052e16; color: #86efac; border: 1px solid #22c55e; }
    .grid { display: grid; gap: 18px; }
    .cards { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .two { grid-template-columns: minmax(0, 1.4fr) minmax(320px, .8fr); }
    .card, .panel { background: rgba(15, 23, 42, .82); border: 1px solid rgba(148, 163, 184, .24); border-radius: 24px; box-shadow: 0 24px 60px rgba(0, 0, 0, .28); }
    .card { padding: 22px; }
    .card span { display: block; color: #9fb0ca; font-size: .9rem; margin-bottom: 10px; }
    .card strong { font-size: 2rem; }
    .panel { padding: 24px; margin-top: 18px; }
    .pill-row { display: flex; flex-wrap: wrap; gap: 10px; }
    .pill { border-radius: 999px; padding: 9px 12px; font-weight: 700; font-size: .88rem; }
    .pill.good { background: #052e16; color: #bbf7d0; }
    .pill.neutral { background: #334155; color: #e2e8f0; }
    .pill.danger { background: #7f1d1d; color: #fecaca; }
    .table-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; font-size: .92rem; }
    th, td { text-align: left; padding: 12px 10px; border-bottom: 1px solid rgba(148, 163, 184, .16); vertical-align: top; }
    th { color: #93c5fd; font-weight: 800; }
    .details { display: grid; grid-template-columns: 150px 1fr; gap: 10px 14px; }
    dt { color: #9fb0ca; }
    dd { margin: 0; font-weight: 700; }
    @media (max-width: 900px) { header { align-items: flex-start; flex-direction: column; } .cards, .two { grid-template-columns: 1fr; } }
    """
