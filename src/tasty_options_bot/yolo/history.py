"""Reconcile broker fills into an audit-friendly YOLO trade ledger.

Pure functions over tastytrade /transactions payloads: no I/O, no orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from tasty_options_bot.yolo.settings import parse_occ_option_symbol

_FEE_FIELDS = ("commission", "regulatory-fees", "clearing-fees")


@dataclass(frozen=True)
class TradeFill:
    """One broker fill (a single transaction row)."""

    executed_at: datetime
    action: str
    option_symbol: str
    quantity: int
    price: float
    value: float
    value_effect: str
    fees: float
    order_id: int | None = None

    @property
    def is_opening(self) -> bool:
        return self.action.lower().startswith("buy to open")

    @property
    def is_closing(self) -> bool:
        return self.action.lower().startswith("sell to close")


@dataclass(frozen=True)
class TradeRecord:
    """All fills for one option symbol, reconciled into a ledger row."""

    option_symbol: str
    underlying_symbol: str
    opened_at: datetime
    last_activity_at: datetime
    bought_quantity: int
    sold_quantity: int
    avg_entry_price: float
    avg_exit_price: float | None
    gross_realized: float
    total_fees: float
    net_realized: float

    @property
    def open_quantity(self) -> int:
        return self.bought_quantity - self.sold_quantity

    @property
    def status(self) -> str:
        if self.sold_quantity == 0:
            return "OPEN"
        if self.open_quantity == 0:
            return "CLOSED"
        return "PARTIAL"

    @property
    def is_win(self) -> bool | None:
        if self.status == "OPEN":
            return None
        return self.net_realized > 0


def parse_broker_transactions(raw_items: list[dict]) -> list[TradeFill]:
    """Parse tastytrade transaction rows into fills. Skips non-trades."""
    fills: list[TradeFill] = []
    for item in raw_items:
        if str(item.get("transaction-type", "")) != "Trade":
            continue
        symbol = str(item.get("symbol", "")).strip()
        if parse_occ_option_symbol(symbol) is None:
            continue
        executed_raw = str(item.get("executed-at", "")).replace("Z", "+00:00")
        try:
            executed_at = datetime.fromisoformat(executed_raw)
        except ValueError:
            continue
        fees = round(
            sum(float(item.get(key, 0) or 0) for key in _FEE_FIELDS), 4
        )
        fills.append(
            TradeFill(
                executed_at=executed_at,
                action=str(item.get("action", "")),
                option_symbol=str(item.get("symbol", "")),
                quantity=int(float(item.get("quantity", 0) or 0)),
                price=float(item.get("price", 0) or 0),
                value=float(item.get("value", 0) or 0),
                value_effect=str(item.get("value-effect", "")),
                fees=fees,
                order_id=item.get("order-id"),
            )
        )
    fills.sort(key=lambda fill: fill.executed_at)
    return fills


def build_trade_records(fills: list[TradeFill]) -> list[TradeRecord]:
    """Group fills per option symbol into ledger rows, newest activity first."""
    by_symbol: dict[str, list[TradeFill]] = {}
    for fill in fills:
        by_symbol.setdefault(fill.option_symbol, []).append(fill)

    records: list[TradeRecord] = []
    for symbol, symbol_fills in by_symbol.items():
        parsed = parse_occ_option_symbol(symbol)
        underlying = parsed.underlying_symbol if parsed else symbol.split()[0]
        symbol_fills.sort(key=lambda fill: fill.executed_at)

        opens = [fill for fill in symbol_fills if fill.is_opening]
        closes = [fill for fill in symbol_fills if fill.is_closing]
        if not opens:
            continue

        bought_qty = sum(fill.quantity for fill in opens)
        sold_qty = sum(fill.quantity for fill in closes)
        avg_entry = (
            sum(fill.price * fill.quantity for fill in opens) / bought_qty
            if bought_qty
            else 0.0
        )
        avg_exit = (
            sum(fill.price * fill.quantity for fill in closes) / sold_qty
            if sold_qty
            else None
        )
        gross_realized = (
            round((avg_exit - avg_entry) * 100 * sold_qty, 2)
            if avg_exit is not None
            else 0.0
        )
        total_fees = round(sum(fill.fees for fill in symbol_fills), 2)
        net_realized = (
            round(gross_realized - total_fees, 2) if sold_qty else 0.0
        )

        records.append(
            TradeRecord(
                option_symbol=symbol,
                underlying_symbol=underlying,
                opened_at=symbol_fills[0].executed_at,
                last_activity_at=symbol_fills[-1].executed_at,
                bought_quantity=bought_qty,
                sold_quantity=sold_qty,
                avg_entry_price=round(avg_entry, 4),
                avg_exit_price=round(avg_exit, 4) if avg_exit is not None else None,
                gross_realized=gross_realized,
                total_fees=total_fees,
                net_realized=net_realized,
            )
        )

    records.sort(key=lambda record: record.last_activity_at, reverse=True)
    return records
